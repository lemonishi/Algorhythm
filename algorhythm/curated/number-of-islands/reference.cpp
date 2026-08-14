class Solution {
public:
    int numIslands(vector<vector<char>>& grid) {
        if (grid.empty() || grid[0].empty()) return 0;
        int rows = grid.size(), cols = grid[0].size(), islands = 0;
        for (int r = 0; r < rows; r++) {
            for (int c = 0; c < cols; c++) {
                if (grid[r][c] != '1') continue;
                islands++;
                stack<pair<int, int>> st;
                st.push({r, c});
                while (!st.empty()) {
                    auto [row, col] = st.top();
                    st.pop();
                    if (row < 0 || row >= rows || col < 0 || col >= cols) continue;
                    if (grid[row][col] != '1') continue;
                    grid[row][col] = '0';
                    st.push({row + 1, col});
                    st.push({row - 1, col});
                    st.push({row, col + 1});
                    st.push({row, col - 1});
                }
            }
        }
        return islands;
    }
};
