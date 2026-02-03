### 1. Deterministic Planning
- Single `have_enough` method eliminates exponential branching
- Returns only the best method per task (no backtracking)

### 2. The Heuristic
Prunes branches under these conditions:
 - Branch is out of time
 - Trying to make a tool that has already been made
 - Producing same tool back to back without checking

### 3. Reordering scheme
Certain tools are preferred for tasks
- **Wood**: Uses punch (no tool required)
- **Cobble**: Prefers stone_pickaxe (2x faster), upgrades when possible
- **Ore**: Prefers iron_pickaxe (2x faster than stone)
- **Coal**: Uses best available pickaxe

Consumed items are processed by dependency depth:
- Complex items first (ingot, ore, coal, cobble)
- Simple items last (stick, plank, wood)