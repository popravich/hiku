from __future__ import absolute_import

from graphql.language import ast
from graphql.language.ast import NonNullType
from graphql.language.parser import parse

from ..utils import const
from ..query import Node, Field, Link, merge


class NodeVisitor(object):

    def visit(self, obj):
        if not isinstance(obj, ast.Node):
            raise TypeError('Unknown node type: {!r}'.format(obj))
        visit_method = getattr(self, 'visit_{}'.format(obj.__class__.__name__),
                               None)
        if visit_method is None:
            raise NotImplementedError('Not implemented node type: {!r}'
                                      .format(obj))
        return visit_method(obj)

    def visit_Document(self, obj):
        for definition in obj.definitions:
            self.visit(definition)

    def visit_OperationDefinition(self, obj):
        self.visit(obj.selection_set)

    def visit_FragmentDefinition(self, obj):
        self.visit(obj.selection_set)

    def visit_SelectionSet(self, obj):
        for i in obj.selections:
            self.visit(i)

    def visit_Field(self, obj):
        pass

    def visit_FragmentSpread(self, obj):
        pass

    def visit_InlineFragment(self, obj):
        self.visit(obj.selection_set)


class OperationGetter(NodeVisitor):

    def __init__(self, operation_name=None):
        self._operations = {}
        self._operation_name = operation_name

    @classmethod
    def get(cls, doc, operation_name=None):
        self = cls(operation_name=operation_name)
        self.visit(doc)
        if not self._operations:
            raise TypeError('No operations in the document')

        if self._operation_name is None:
            if len(self._operations) > 1:
                raise TypeError('Document should contain exactly one operation '
                                'when no operation name was provided')
            return next(iter(self._operations.values()))
        else:
            try:
                return self._operations[self._operation_name]
            except KeyError:
                raise ValueError('Undefined operation name: {!r}'
                                 .format(self._operation_name))

    def visit_FragmentDefinition(self, obj):
        pass  # skip visit here

    def visit_OperationDefinition(self, obj):
        name = obj.name.value if obj.name is not None else None
        if name in self._operations:
            raise TypeError('Duplicate operation definition: {!r}'
                            .format(name))
        self._operations[name] = obj


class FragmentsCollector(NodeVisitor):

    def __init__(self):
        self.fragments_map = {}

    def visit_OperationDefinition(self, obj):
        pass  # not interested in operations here

    def visit_FragmentDefinition(self, obj):
        if obj.name.value in self.fragments_map:
            raise TypeError('Duplicated fragment name: "{}"'
                            .format(obj.name.value))
        self.fragments_map[obj.name.value] = obj


class SelectionSetVisitMixin(object):

    def transform_fragment(self, name):
        raise NotImplementedError(type(self))

    @property
    def query_variables(self):
        raise NotImplementedError(type(self))

    @property
    def query_name(self):
        raise NotImplementedError(type(self))

    def lookup_variable(self, name):
        try:
            return self.query_variables[name]
        except KeyError:
            raise TypeError('Variable ${} is not defined in query {}'
                            .format(name, self.query_name or '<unnamed>'))

    def visit_SelectionSet(self, obj):
        for i in obj.selections:
            for j in self.visit(i):
                yield j

    def visit_Field(self, obj):
        if obj.arguments:
            options = {arg.name.value: self.visit(arg.value)
                       for arg in obj.arguments}
        else:
            options = None

        if obj.alias is not None:
            alias = obj.alias.value
        else:
            alias = None

        if obj.selection_set is None:
            yield Field(obj.name.value, options=options, alias=alias)
        else:
            node = Node(list(self.visit(obj.selection_set)))
            yield Link(obj.name.value, node, options=options, alias=alias)

    def visit_Variable(self, obj):
        return self.lookup_variable(obj.name.value)

    def _visit_scalar(self, obj):
        return obj.value

    def visit_IntValue(self, obj):
        return int(obj.value)

    def visit_FloatValue(self, obj):
        return float(obj.value)

    def visit_StringValue(self, obj):
        return obj.value

    def visit_BooleanValue(self, obj):
        return obj.value

    def visit_EnumValue(self, obj):
        return obj.value

    def visit_ListValue(self, obj):
        return [self.visit(i) for i in obj.values]

    def visit_ObjectValue(self, obj):
        return {f.name.value: self.visit(f.value) for f in obj.fields}

    def visit_FragmentSpread(self, obj):
        assert not obj.directives, obj.directives
        for i in self.transform_fragment(obj.name.value):
            yield i

    def visit_InlineFragment(self, obj):
        for i in self.visit(obj.selection_set):
            yield i


class FragmentsTransformer(SelectionSetVisitMixin, NodeVisitor):
    query_name = None
    query_variables = None

    def __init__(self, document, query_name, query_variables):
        collector = FragmentsCollector()
        collector.visit(document)
        self.query_name = query_name
        self.query_variables = query_variables
        self.fragments_map = collector.fragments_map
        self.cache = {}
        self.pending_fragments = set()

    def transform_fragment(self, name):
        return self.visit(self.fragments_map[name])

    def visit_OperationDefinition(self, obj):
        pass  # not interested in operations here

    def visit_FragmentDefinition(self, obj):
        if obj.name.value in self.cache:
            return self.cache[obj.name.value]
        else:
            if obj.name.value in self.pending_fragments:
                raise TypeError('Cyclic fragment usage: "{}"'
                                .format(obj.name.value))
            self.pending_fragments.add(obj.name.value)
            try:
                selection_set = list(self.visit(obj.selection_set))
            finally:
                self.pending_fragments.discard(obj.name.value)
            self.cache[obj.name.value] = selection_set
            return selection_set


class GraphQLTransformer(SelectionSetVisitMixin, NodeVisitor):
    query_name = None
    query_variables = None
    fragments_transformer = None

    def __init__(self, document, variables=None):
        self.document = document
        self.variables = variables

    @classmethod
    def transform(cls, document, op, variables=None):
        visitor = cls(document, variables)
        return visitor.visit(op)

    def transform_fragment(self, name):
        return self.fragments_transformer.transform_fragment(name)

    def visit_OperationDefinition(self, obj):
        variables = self.variables or {}
        query_name = obj.name.value if obj.name else '<unnamed>'
        query_variables = {}
        for var_defn in obj.variable_definitions or ():
            name = var_defn.variable.name.value
            try:
                value = variables[name]  # TODO: check variable type
            except KeyError:
                if var_defn.default_value is not None:
                    value = self.visit(var_defn.default_value)
                elif isinstance(var_defn.type, NonNullType):
                    raise TypeError('Variable "{}" is not provided for query {}'
                                    .format(name, query_name))
                else:
                    value = None
            query_variables[name] = value

        self.query_name = query_name
        self.query_variables = query_variables
        self.fragments_transformer = FragmentsTransformer(self.document,
                                                          self.query_name,
                                                          self.query_variables)
        ordered = obj.operation == 'mutation'
        try:
            node = Node(list(self.visit(obj.selection_set)),
                        ordered=ordered)
        finally:
            self.query_name = None
            self.query_variables = None
            self.fragments_transformer = None
        return merge([node])


def read(src, variables=None, operation_name=None):
    """Reads a query from the GraphQL document

    Example:

    .. code-block:: python

        query = read('{ foo bar }')
        result = engine.execute(graph, query)

    :param str src: GraphQL query
    :param dict variables: query variables
    :param str operation_name: Name of the operation to execute
    :return: :py:class:`hiku.query.Node`, ready to execute query object
    """
    doc = parse(src)
    op = OperationGetter.get(doc, operation_name=operation_name)
    if op.operation != 'query':
        raise TypeError('Only "query" operations are supported, '
                        '"{}" operation was provided'
                        .format(op.operation))

    return GraphQLTransformer.transform(doc, op, variables)


class OperationType(object):
    """Enumerates GraphQL operation types"""
    #: query operation
    QUERY = const('OperationType.QUERY')
    #: mutation operation
    MUTATION = const('OperationType.MUTATION')
    #: subscription operation
    SUBSCRIPTION = const('OperationType.SUBSCRIPTION')


class Operation(object):
    """Represents requested GraphQL operation"""
    def __init__(self, type_, query, name=None):
        #: type of the operation
        self.type = type_
        #: operation's query
        self.query = query
        #: optional name of the operation
        self.name = name


_operations_map = {
    'query': OperationType.QUERY,
    'mutation': OperationType.MUTATION,
    'subscription': OperationType.SUBSCRIPTION,
}


def read_operation(src, variables=None, operation_name=None):
    """Reads an operation from the GraphQL document

    Example:

    .. code-block:: python

        op = read_operation('{ foo bar }')
        if op.type is OperationType.QUERY:
            result = engine.execute(query_graph, op.query)

    :param str src: GraphQL document
    :param dict variables: query variables
    :param str operation_name: Name of the operation to execute
    :return: :py:class:`Operation`
    """
    doc = parse(src)
    op = OperationGetter.get(doc, operation_name=operation_name)
    query = GraphQLTransformer.transform(doc, op, variables)
    type_ = _operations_map.get(op.operation)
    name = op.name.value if op.name else None
    if type_ is None:
        raise TypeError('Unsupported operation type: {}'.format(op.operation))
    else:
        return Operation(type_, query, name)
