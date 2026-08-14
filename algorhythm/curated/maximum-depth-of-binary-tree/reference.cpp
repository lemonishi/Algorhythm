// Hand-written: neetcode-gh's file closes the class with `}` instead of
// `};`, so nothing that includes it will compile.
class Solution {
public:
    int maxDepth(TreeNode* root) {
        if (root == nullptr) return 0;
        return 1 + max(maxDepth(root->left), maxDepth(root->right));
    }
};
