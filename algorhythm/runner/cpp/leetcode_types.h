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

// -- cycles and graphs ------------------------------------------------------
// JSON cannot express either shape, so both are built from a flat literal.

// `pos` is the index the tail points back to, or -1 for no cycle — LeetCode's
// own notation for linked-list-cycle.
inline ListNode *buildListCycle(const vector<int> &vals, int pos) {
    if (vals.empty()) return nullptr;
    vector<ListNode *> nodes;
    for (int v : vals) nodes.push_back(new ListNode(v));
    for (size_t i = 0; i + 1 < nodes.size(); ++i) nodes[i]->next = nodes[i + 1];
    if (pos >= 0 && pos < (int)nodes.size()) nodes.back()->next = nodes[pos];
    return nodes[0];
}

// Adjacency lists, 1-indexed the way LeetCode writes them: entry i lists the
// neighbours of the node whose val is i+1.
struct Node {
    int val;
    vector<Node *> neighbors;
    Node() : val(0) {}
    Node(int x) : val(x) {}
    Node(int x, vector<Node *> n) : val(x), neighbors(n) {}
};

inline Node *buildGraph(const vector<vector<int>> &adj) {
    if (adj.empty()) return nullptr;
    vector<Node *> nodes;
    for (size_t i = 0; i < adj.size(); ++i) nodes.push_back(new Node((int)i + 1));
    for (size_t i = 0; i < adj.size(); ++i)
        for (int neighbour : adj[i]) nodes[i]->neighbors.push_back(nodes[neighbour - 1]);
    return nodes[0];
}

// Walks from `node` and re-emits the adjacency lists in val order, so the
// result compares equal to the input for a correct clone.
inline string repr(Node *node) {
    if (!node) return "[]";
    map<int, vector<int>> adj;
    queue<Node *> q;
    set<int> seen;
    q.push(node);
    seen.insert(node->val);
    while (!q.empty()) {
        Node *cur = q.front();
        q.pop();
        vector<int> vals;
        for (Node *n : cur->neighbors) {
            vals.push_back(n->val);
            if (!seen.count(n->val)) { seen.insert(n->val); q.push(n); }
        }
        adj[cur->val] = vals;
    }
    string out = "[";
    bool first = true;
    for (auto &entry : adj) {
        if (!first) out += ",";
        out += repr(entry.second);
        first = false;
    }
    return out + "]";
}
