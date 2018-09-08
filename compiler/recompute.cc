#include "recompute.h"

#include <map>
#include <memory>
#include <queue>

#include <compiler/graph.h>
#include <compiler/graph_builder.h>
#include <compiler/node.h>

namespace oniku {

namespace {

std::map<const Node*, int> GetDistancesOfNodes(const Graph& graph) {
    std::map<const Node*, int> distances;
    std::map<Node*, int> input_counts = graph.GetUsedCounts();
    std::queue<std::pair<Node*, int>> q;

    auto make_value_ready = [&input_counts, &q](const Value* value, int distance) {
        for (Node* node : value->users()) {
            auto found = input_counts.find(node);
            if (found == input_counts.end())
                continue;
            int cnt = --found->second;
            CHECK_LE(0, cnt) << node->DebugString();
            if (cnt != 0)
                continue;
            q.push(std::make_pair(node, distance));
        }
    };

    for (const auto& p : input_counts) {
        if (p.second == 0) {
            q.push(std::make_pair(p.first, 0));
        }
    }
    for (const Value* value : graph.input_values()) {
        make_value_ready(value, 0);
    }

    while (!q.empty()) {
        const Node* node = q.front().first;
        const int distance = q.front().second;
        q.pop();

        CHECK(distances.emplace(node, distance).second) << node->DebugString();
        for (Value* output : node->outputs()) {
            make_value_ready(output, distance + 1);
        }
    }
    return distances;
}

int GetDistance(const Node* node, const std::map<const Node*, int>& distances) {
    auto found = distances.find(node);
    if (found == distances.end()) return -1;
    return found->second;
}

}  //  namespace

void GetReluRecompute(Graph* graph) {
    const std::map<const Node*, int> distances = GetDistancesOfNodes(*graph);
    constexpr int kSoon = 3;

    for (const std::unique_ptr<Node>& node : graph->nodes()) {
        if (node->op_type() != Node::kRelu) continue;

        int relu_dist = GetDistance(node.get(), distances);
        if (relu_dist < 0) continue;
        // It's not worth recomputing Relu if this Relu is the only
        // user of the input value.
        if (node->inputs()[0]->users().size() == 1) continue;
        Value* relu_output = node->outputs()[0];
        int num_near_users = 0;
        std::multimap<int, Node*> far_users;
        for (Node* user : relu_output->users()) {
            int dist = GetDistance(user, distances) - relu_dist;
            if (dist < 0) continue;
            if (dist <= kSoon) {
                ++num_near_users;
            } else {
                far_users.emplace(dist, user);
            }
        }
        if (far_users.empty() || !num_near_users) continue;

        // std::cerr << "RecomputeRelu: " << relu_output->GetNBytes() / 1000 << "kB" << " " << node->DebugString() << std::endl;
        GraphBuilder gb(graph, "RecomputeRelu", relu_output);
        Value* recomputed = gb.Op(Node::kRelu, node->inputs());
        for (const auto& p : far_users) {
            Node* user = p.second;
            relu_output->DetachUser(user);
            recomputed->AddUser(user);
            user->ReplaceInput(relu_output, recomputed);
        }
    }
}

}  // namespace oniku
