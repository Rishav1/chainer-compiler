#pragma once

#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include <onnx/onnx-ml.pb.h>

namespace oniku {

class Graph;

class Model {
public:
    explicit Model(const onnx::ModelProto& xmodel);
    ~Model();

    Model(const Model&) = delete;
    Model& operator=(const Model&) = delete;

    void ToONNX(onnx::ModelProto* xmodel) const;

    const Graph& graph() const {
        return *graph_;
    }
    Graph* mutable_graph() {
        return graph_.get();
    }

    int64_t ir_version() const {
        return ir_version_;
    }
    const std::vector<onnx::OperatorSetIdProto>& opset_import() const {
        return opset_import_;
    }
    const std::string& producer_name() const {
        return producer_name_;
    }
    const std::string& producer_version() const {
        return producer_version_;
    }
    const std::string& domain() const {
        return domain_;
    }
    int64_t model_version() const {
        return model_version_;
    }
    const std::string& doc_string() const {
        return doc_string_;
    }
    const std::map<std::string, std::string>& metadata_props() const {
        return metadata_props_;
    }

private:
    int64_t ir_version_;
    std::vector<onnx::OperatorSetIdProto> opset_import_;
    std::string producer_name_;
    std::string producer_version_;
    std::string domain_;
    int64_t model_version_;
    std::string doc_string_;
    std::unique_ptr<Graph> graph_;
    std::map<std::string, std::string> metadata_props_;
};

}  // namespace oniku
