import time

import pyhop
import json


def have_enough_method(state, ID, item, num):
	# single method to eliminate branching
	if getattr(state, item)[ID] >= num:
		return []
	return [('produce', ID, item), ('have_enough', ID, item, num)]

pyhop.declare_methods('have_enough', have_enough_method)

def produce(state, ID, item):
	return [('produce_{}'.format(item), ID)]

pyhop.declare_methods('produce', produce)

# global storage for recipe info (needed by reorder_methods)
recipe_info = {}

def make_method(name, rule):
	# priority: complex items first
	item_priority = {
		'ingot': 100, 'ore': 90, 'coal': 80, 'cobble': 70,
		'stick': 30, 'plank': 20, 'wood': 10,
	}
	
	consumes = rule['Consumes'] if 'Consumes' in rule else {}
	consumes_sorted = sorted(
		consumes.items(),
		key=lambda kv: -item_priority.get(kv[0], 50)
	)
	
	def method(state, ID):
		prerequisites = []
		# add required tools
		if 'Requires' in rule:
			for tool, num in sorted(rule['Requires'].items()):
				prerequisites.append(('have_enough', ID, tool, num))
		# add consumed items (sorted by priority)
		for item, num in consumes_sorted:
			prerequisites.append(('have_enough', ID, item, num))
		op_name = 'op_' + name.replace(' ', '_')
		return prerequisites + [(op_name, ID)]
	return method

def declare_methods(data):
	global recipe_info
	recipe_info = {}
	
	# group recipes by product
	recipes_by_product = {}
	for recipe_name, rule in data['Recipes'].items():
		if 'Produces' in rule:
			for item, num in rule['Produces'].items():
				if item not in recipes_by_product:
					recipes_by_product[item] = []
				recipes_by_product[item].append((recipe_name, rule))
		# store recipe info for reorder_methods
		recipe_info[recipe_name.replace(' ', '_')] = rule
	
	# tool complexity for sorting
	tool_complexity = {
		'bench': 0, 'wooden_pickaxe': 1, 'wooden_axe': 1,
		'stone_pickaxe': 2, 'stone_axe': 2,
		'furnace': 3, 'iron_pickaxe': 4, 'iron_axe': 4,
	}
	
	def recipe_priority(entry):
		recipe_name, rule = entry
		requires = rule['Requires'] if 'Requires' in rule else {}
		tool_cost = sum(tool_complexity.get(t, 10) for t in requires)
		return (tool_cost, rule['Time'])
	
	# create methods for each product
	for item, recipe_list in recipes_by_product.items():
		sorted_recipes = sorted(recipe_list, key=recipe_priority)
		methods = []
		for recipe_name, rule in sorted_recipes:
			method = make_method(recipe_name, rule)
			method.__name__ = recipe_name.replace(' ', '_')
			methods.append(method)
		pyhop.declare_methods('produce_{}'.format(item), *methods)

def make_operator(rule):
	def operator(state, ID):
		# check time
		if state.time[ID] < rule['Time']:
			return False
		# check required tools
		if 'Requires' in rule:
			for tool, num in rule['Requires'].items():
				if getattr(state, tool)[ID] < num:
					return False
		# check consumed items
		if 'Consumes' in rule:
			for item, num in rule['Consumes'].items():
				if getattr(state, item)[ID] < num:
					return False
		# apply changes
		state.time[ID] -= rule['Time']
		if 'Produces' in rule:
			for item, num in rule['Produces'].items():
				getattr(state, item)[ID] += num
		if 'Consumes' in rule:
			for item, num in rule['Consumes'].items():
				getattr(state, item)[ID] -= num
		return state
	return operator

def declare_operators(data):
	operators = []
	for recipe_name, rule in data['Recipes'].items():
		op_name = 'op_' + recipe_name.replace(' ', '_')
		operator = make_operator(rule)
		operator.__name__ = op_name
		operators.append(operator)
	pyhop.declare_operators(*operators)

def add_heuristic(data, ID):
	tools = set(data['Tools'])
	
	def heuristic(state, curr_task, tasks, plan, depth, calling_stack):
		# prune if out of time
		if state.time[ID] < 0:
			return True
		
		task_name = curr_task[0]
		if task_name.startswith('produce_'):
			item = task_name[len('produce_'):]
			if item in tools:
				# prune if already have tool
				if getattr(state, item)[ID] >= 1:
					return True
				# prune if recursive tool production
				for prev in calling_stack:
					if prev[0] == task_name:
						return True
		return False
	
	pyhop.add_check(heuristic)

def define_ordering(data, ID):
	tools = set(data['Tools'])
	pickaxe_order = ['iron_pickaxe', 'stone_pickaxe', 'wooden_pickaxe']
	
	tool_complexity = {
		'bench': 0, 'wooden_pickaxe': 1, 'wooden_axe': 1,
		'stone_pickaxe': 2, 'stone_axe': 2,
		'furnace': 3, 'iron_pickaxe': 4, 'iron_axe': 4,
	}
	
	def reorder_methods(state, curr_task, tasks, plan, depth, calling_stack, methods):
		if not curr_task[0].startswith('produce_'):
			return methods
		
		item = curr_task[0][len('produce_'):]
		have_pickaxes = [t for t in pickaxe_order if getattr(state, t)[ID] >= 1]
		
		# wood: use punch (no tool)
		if item == 'wood':
			for m in methods:
				r = recipe_info.get(m.__name__, {})
				if 'Requires' not in r or not r['Requires']:
					return [m]
		
		# cobble: prefer stone_pickaxe (2x faster than wooden)
		if item == 'cobble':
			if have_pickaxes and 'iron_pickaxe' in have_pickaxes:
				target = 'iron_pickaxe'
			elif have_pickaxes and 'stone_pickaxe' in have_pickaxes:
				target = 'stone_pickaxe'
			elif have_pickaxes and 'wooden_pickaxe' in have_pickaxes:
				# try to make stone first unless already making it
				making_stone = any(c[0] == 'produce_stone_pickaxe' for c in calling_stack)
				target = 'wooden_pickaxe' if making_stone else 'stone_pickaxe'
			else:
				target = 'wooden_pickaxe'
			for m in methods:
				r = recipe_info.get(m.__name__, {})
				if 'Requires' in r and target in r['Requires']:
					return [m]
		
		# coal: use best pickaxe we have
		if item == 'coal':
			target = have_pickaxes[0] if have_pickaxes else 'wooden_pickaxe'
			for m in methods:
				r = recipe_info.get(m.__name__, {})
				if 'Requires' in r and target in r['Requires']:
					return [m]
		
		# ore: prefer iron (2 time) over stone (4 time)
		if item == 'ore':
			if have_pickaxes and 'iron_pickaxe' in have_pickaxes:
				target = 'iron_pickaxe'
			else:
				target = 'stone_pickaxe'
			for m in methods:
				r = recipe_info.get(m.__name__, {})
				if 'Requires' in r and target in r['Requires']:
					return [m]
		
		# other items: score by tool availability
		def score(m):
			r = recipe_info.get(m.__name__, {})
			requires = r['Requires'] if 'Requires' in r else {}
			s = r.get('Time', 0)
			for tool in requires:
				have = getattr(state, tool)[ID]
				if have >= 1:
					s -= 100
				else:
					s += tool_complexity.get(tool, 5) * 50
			return s
		
		sorted_methods = sorted(methods, key=score)
		if sorted_methods:
			return [sorted_methods[0]]
		return methods
	
	pyhop.define_ordering(reorder_methods)

def set_up_state(data, ID, initial_items=None, max_time=None):
	state = pyhop.State('state')
	if max_time is not None:
		setattr(state, 'time', {ID: max_time})
	else:
		setattr(state, 'time', {ID: data['Problem']['Time']})
	for item in data['Items']:
		setattr(state, item, {ID: 0})
	for item in data['Tools']:
		setattr(state, item, {ID: 0})
	if initial_items is not None:
		for item, num in initial_items.items():
			setattr(state, item, {ID: num})
	else:
		for item, num in data['Problem']['Initial'].items():
			setattr(state, item, {ID: num})
	return state

def set_up_goals(data, ID, goal_items=None):
	goals = []
	if goal_items is not None:
		for item, num in goal_items.items():
			goals.append(('have_enough', ID, item, num))
	else:
		for item, num in data['Problem']['Goal'].items():
			goals.append(('have_enough', ID, item, num))
	return goals

def initialize_planner(data, ID):
	# reset pyhop state
	pyhop.operators = {}
	pyhop.methods = {}
	pyhop.checks = []
	pyhop.get_custom_method_order = None
	# re-declare base methods
	pyhop.declare_methods('have_enough', have_enough_method)
	pyhop.declare_methods('produce', produce)
	# declare operators and methods from data
	declare_operators(data)
	declare_methods(data)
	add_heuristic(data, ID)
	define_ordering(data, ID)

if __name__ == '__main__':
	import sys
	rules_filename = 'crafting.json'
	if len(sys.argv) > 1:
		rules_filename = sys.argv[1]

	with open(rules_filename) as f:
		data = json.load(f)

	ID = 'agent'
	initialize_planner(data, ID)
	state = set_up_state(data, ID)
	goals = set_up_goals(data, ID)

	#sys.setrecursionlimit(10000)
	start_time = time.thread_time()
	result = pyhop.pyhop(state, goals, verbose=1)
	stop_time = time.thread_time()
	time_elapsed = stop_time - start_time

	if result:
		print("\nPlan found with {} steps:".format(len(result)))
		for i, step in enumerate(result):
			print("  {}. {}".format(i+1, step))
		print("")
		# print("Planner Time Taken: ", state.time[ID] - pyhop.end_time)
		print("Real Time Taken: ", time_elapsed)
	else:
		print("\nNo plan found.")
