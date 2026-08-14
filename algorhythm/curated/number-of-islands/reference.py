# Hand-written: neetcode-gh's file ships a SolutionBFS variant with broken
# indentation, so the whole module fails to parse and the problem ends up
# with no oracle cases and nothing for the reviewer to compare against.
class Solution:
    def numIslands(self, grid: List[List[str]]) -> int:
        if not grid or not grid[0]:
            return 0

        rows, cols = len(grid), len(grid[0])
        seen = set()
        islands = 0

        def sink(start_row, start_col):
            stack = [(start_row, start_col)]
            while stack:
                row, col = stack.pop()
                if not (0 <= row < rows and 0 <= col < cols):
                    continue
                if (row, col) in seen or grid[row][col] != "1":
                    continue
                seen.add((row, col))
                stack.extend(
                    [(row + 1, col), (row - 1, col), (row, col + 1), (row, col - 1)]
                )

        for row in range(rows):
            for col in range(cols):
                if grid[row][col] == "1" and (row, col) not in seen:
                    islands += 1
                    sink(row, col)

        return islands
