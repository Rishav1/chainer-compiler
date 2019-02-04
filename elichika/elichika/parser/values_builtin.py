from elichika.parser import nodes
from elichika.parser import values
from elichika.parser import functions
from elichika.parser.graphs import Graph

import chainer.links

def is_builtin_chainer_link(value) -> 'bool':
    if isinstance(value, chainer.links.Linear):
        return True
    if isinstance(value, chainer.links.Convolution2D):
        return True
    return False

class ChainerLinkFunction(functions.FunctionBase):
    def __init__(self, owner):
        super().__init__()
        self.name = '__call__'
        self.owner = owner

    def vcall(self, module : 'values.Field', graph : 'Graph', inst : 'Object', args = [], line = -1):
        node = nodes.NodeCall(self, [v.obj.get_value() for v in args], line)
        graph.add_node(node)
        value = values.TensorValue()

        # TODO refactor
        if(isinstance(self.owner.inst, chainer.links.Linear)):
            cn = self.owner.inst # type: chainer.links.Linear
            if isinstance(args[0].obj.get_value(), values.TensorValue) and len(args[0].obj.get_value().shape) >= 2:
                value.shape = (args[0].obj.get_value().shape[0], cn.out_size)

        if(isinstance(self.owner.inst, chainer.links.Convolution2D)):
            value = functions.generate_tensor_value_with_undefined_shape_size(args[0].obj.get_value())

        node.set_outputs([value])
        return values.Object(value)

class ChainerLinkInstance(values.Instance):
    def __init__(self, module : 'Field', inst):
        super().__init__(module, inst, None)
        self.callable = True

    def apply_to_object(self, obj : 'values.Object'):
        self.func = values.Object(values.FuncValue(ChainerLinkFunction(self), obj))
        obj.get_field().get_attribute('forward').revise(self.func)
