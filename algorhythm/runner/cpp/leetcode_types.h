// Types and serialization shared by every generated C++ harness.
// Kept header-only so the generated main.cpp is a single translation unit.
#pragma once

#include <algorithm>
#include <climits>
#include <cmath>
#include <deque>
#include <functional>
#include <iostream>
#include <map>
#include <numeric>
#include <queue>
#include <set>
#include <sstream>
#include <stack>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

using namespace std;

// Sentinel for a null slot in a level-order array literal.
static const int NUL = INT_MIN;

struct TreeNode {
    int val;
    TreeNode *left;
    TreeNode *right;
    TreeNode() : val(0), left(nullptr), right(nullptr) {}
    TreeNode(int x) : val(x), left(nullptr), right(nullptr) {}
    TreeNode(int x, TreeNode *l, TreeNode *r) : val(x), left(l), right(r) {}
};

struct ListNode {
    int val;
    ListNode *next;
    ListNode() : val(0), next(nullptr) {}
    ListNode(int x) : val(x), next(nullptr) {}
    ListNode(int x, ListNode *n) : val(x), next(n) {}
};

inline TreeNode *buildTree(const vector<int> &vals) {
    if (vals.empty() || vals[0] == NUL) return nullptr;
    TreeNode *root = new TreeNode(vals[0]);
    queue<TreeNode *> q;
    q.push(root);
    size_t i = 1;
    while (!q.empty() && i < vals.size()) {
        TreeNode *node = q.front();
        q.pop();
        if (i < vals.size()) {
            int v = vals[i++];
            if (v != NUL) { node->left = new TreeNode(v); q.push(node->left); }
        }
        if (i < vals.size()) {
            int v = vals[i++];
            if (v != NUL) { node->right = new TreeNode(v); q.push(node->right); }
        }
    }
    return root;
}

inline ListNode *buildList(const vector<int> &vals) {
    ListNode head(0);
    ListNode *tail = &head;
    for (int v : vals) { tail->next = new ListNode(v); tail = tail->next; }
    return head.next;
}

// -- canonical serialization ------------------------------------------------
// Must match algorhythm.runner.cpp_runner.canonical() byte for byte.

inline string repr(int v) { return to_string(v); }
inline string repr(long long v) { return to_string(v); }
inline string repr(bool v) { return v ? "true" : "false"; }
inline string repr(char v) { return string("\"") + v + "\""; }

inline string repr(double v) {
    ostringstream os;
    os.precision(5);
    os << fixed << v;
    return os.str();
}

inline string repr(const string &v) { return "\"" + v + "\""; }

template <typename T>
inline string repr(const vector<T> &items) {
    string out = "[";
    for (size_t i = 0; i < items.size(); ++i) {
        if (i) out += ",";
        out += repr(items[i]);
    }
    return out + "]";
}

inline string repr(TreeNode *root) {
    vector<string> out;
    queue<TreeNode *> q;
    q.push(root);
    while (!q.empty()) {
        TreeNode *node = q.front();
        q.pop();
        if (!node) { out.push_back("null"); continue; }
        out.push_back(to_string(node->val));
        q.push(node->left);
        q.push(node->right);
    }
    while (!out.empty() && out.back() == "null") out.pop_back();
    string joined = "[";
    for (size_t i = 0; i < out.size(); ++i) { if (i) joined += ","; joined += out[i]; }
    return joined + "]";
}

inline string repr(ListNode *head) {
    string out = "[";
    bool first = true;
    for (ListNode *n = head; n; n = n->next) {
        if (!first) out += ",";
        out += to_string(n->val);
        first = false;
    }
    return out + "]";
}
