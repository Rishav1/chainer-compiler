#if ONIKU_ENABLE_TVM
#include <map>

#include <chainerx/array.h>
#include <chainerx/routines/creation.h>
#include <chainerx/shape.h>

#include <chainerx/cuda/cuda_device.h>
#include <chainerx/native/native_device.h>

#include <dlpack/dlpack.h>
#include <tvm/runtime/module.h>
#include <tvm/runtime/packed_func.h>

#include <common/strutil.h>

#else

#include <common/log.h>

#endif

#include <runtime/gen_xcvm_ops.h>

namespace oniku {
namespace runtime {

#if ONIKU_ENABLE_TVM

namespace {

DLContext GetDLContext(const chainerx::Array& array) {
    const int index = array.device().index();
    if (dynamic_cast<const chainerx::cuda::CudaDevice*>(&array.device())) {
        return DLContext{kDLGPU, index};
    } else if (dynamic_cast<const chainerx::native::NativeDevice*>(&array.device())) {
        return DLContext{kDLCPU, index};
    } else {
        CHECK(false) << "Unknown ChainerX device: " << array.device().name();
    }
    return DLContext{};
}

DLDataType GetDLDataType(const chainerx::Array& array) {
    switch (array.dtype()) {
    case chainerx::Dtype::kBool:
        return DLDataType{kDLUInt, 1, 1};
    case chainerx::Dtype::kInt8:
        return DLDataType{kDLInt, 8, 1};
    case chainerx::Dtype::kInt16:
        return DLDataType{kDLInt, 16, 1};
    case chainerx::Dtype::kInt32:
        return DLDataType{kDLInt, 32, 1};
    case chainerx::Dtype::kInt64:
        return DLDataType{kDLInt, 64, 1};
    case chainerx::Dtype::kUInt8:
        return DLDataType{kDLUInt, 8, 1};
    case chainerx::Dtype::kFloat32:
        return DLDataType{kDLFloat, 32, 1};
    case chainerx::Dtype::kFloat64:
        return DLDataType{kDLFloat, 64, 1};
    default:
        CHECK(false) << array.dtype();
    }
    return DLDataType{};
}

void FillDLTensor(const chainerx::Array& array, DLTensor* tensor) {
    CHECK(array.IsContiguous());
    tensor->data = array.raw_data();
    tensor->ctx = GetDLContext(array);
    tensor->ndim = array.shape().size();
    tensor->dtype = GetDLDataType(array);
    tensor->shape = const_cast<int64_t*>(array.shape().data());
    tensor->strides = nullptr;
    tensor->byte_offset = 0;
}

tvm::runtime::PackedFunc LoadPackedFunc(const std::string& dso_filename) {
    tvm::runtime::Module dso = tvm::runtime::Module::LoadFromFile(dso_filename);
    tvm::runtime::PackedFunc fn = dso.GetFunction("tvm_op");
    CHECK(fn != nullptr) << dso_filename;
    return fn;
}

}  // namespace

class TVMOp::TVMImpl {
public:
    tvm::runtime::PackedFunc fn;
};

#endif

void TVMOp::InitImpl() {
#if ONIKU_ENABLE_TVM
    impl_ = new TVMImpl();
    impl_->fn = LoadPackedFunc(dso_filename);
#endif
}

std::vector<chainerx::Array> TVMOp::RunImpl(oniku::runtime::XCVMState* st, const std::vector<chainerx::Array>& orig_inputs) {
#if ONIKU_ENABLE_TVM
    CHECK(!inputs.empty());
    auto& device = orig_inputs[0].device();

    // TODO(hamaji): Set output_dtype in TVMOp.
    chainerx::Dtype dtype = orig_inputs[0].dtype();

    // Validate inputs.
    std::vector<chainerx::Array> inputs;
    for (chainerx::Array input : orig_inputs) {
        if (!input.IsContiguous()) {
            input = chainerx::Copy(input);
        }
        inputs.push_back(input);
    }

    std::vector<chainerx::Array> outputs;
    for (int i = 0; i < num_outputs; ++i) {
        outputs.push_back(chainerx::Empty(chainerx::Shape(output_shape), dtype, device));
    }

    size_t num_args = outputs.size() + inputs.size();
    std::vector<DLTensor> tensors(num_args);
    for (size_t i = 0; i < outputs.size(); ++i) {
        FillDLTensor(outputs[i], &tensors[i]);
    }
    for (size_t i = 0; i < inputs.size(); ++i) {
        FillDLTensor(inputs[i], &tensors[outputs.size() + i]);
    }

    TVMValue tvm_values[num_args];
    int tvm_type_codes[num_args];
    auto args_setter = tvm::runtime::TVMArgsSetter(tvm_values, tvm_type_codes);
    for (size_t i = 0; i < tensors.size(); ++i) {
        args_setter(i, &tensors[i]);
    }

    tvm::runtime::TVMArgs tvm_args(tvm_values, tvm_type_codes, num_args);
    tvm::runtime::TVMRetValue tvm_ret;
    impl_->fn.CallPacked(tvm_args, &tvm_ret);

    return outputs;

#else
    CHECK(false) << "Set -DONIKU_ENABLE_TVM=ON: filename=" << dso_filename;
#endif
}

}  // namespace runtime
}  // namespace oniku