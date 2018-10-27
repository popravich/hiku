Using GraphQL
=============

.. note:: Hiku is a general-purpose library to expose data as a graph of linked
  nodes. And it is possible to implement GraphQL server using Hiku. But it is
  wrong to say that Hiku is an implementation of GraphQL specification.

To implement GraphQL server we will have to:

  - add GraphQL introspection into our graph definition
  - read GraphQL query
  - validate query against graph definition
  - execute query using Engine
  - denormalize result into simple data structure
  - serialize result and send back to the client


Graphs definition
~~~~~~~~~~~~~~~~~

In GraphQL several root operation types


Introspection
~~~~~~~~~~~~~

.. automodule:: hiku.introspection.graphql
  :members: GraphQLIntrospection, AsyncGraphQLIntrospection

Incompatible with GraphQL types are represented as :py:class:`hiku.types.Any`
type.

Record data types are represented as interfaces and input objects with
distinct prefixes. Given these data types:

.. code-block:: python

  graph = Graph([...], data_types={'Foo': Record[{'x': Integer}]})

You will see ``Foo`` data type as:

.. code-block:: javascript

  interface IFoo {
    x: Integer
  }

  input IOFoo {
    x: Integer
  }

This is because Hiku's data types universally can be used in fields and
options definition.

Read query
~~~~~~~~~~

There are two options:

  - read simple queries, when only query operations are expected
  - read operations, when different operations are expected: queries, mutations,
    etc.

.. automodule:: hiku.readers.graphql
    :members: read, read_operation, Operation, OperationType

Validate query
~~~~~~~~~~~~~~

As every other query, GraphQL queries should be validated and errors can be
sent back to the client:

.. code-block:: python

  from hiku.validate.query import validate

  def handler(request):
      ...  # read
      errors = validate(graph, query)
      if errors:
          return {'errors': [{'message': e} for e in errors]}
      ...  # execute

Query execution
~~~~~~~~~~~~~~~

Depending on operation type,


Denormalize result
~~~~~~~~~~~~~~~~~~

Most common serialization format for GraphQL is JSON. But in order to serialize
execution result into JSON, it should be denormalized, to replace references
(possibly cyclic) with actual data:

.. code-block:: python

  from hiku.result import denormalize

  def handler(request):
      ... # execute
      result = denormalize(graph, result)
      return response.json(result)

.. _graphql-core: https://github.com/graphql-python/graphql-core
