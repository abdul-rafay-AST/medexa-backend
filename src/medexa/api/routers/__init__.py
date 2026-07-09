"""FastAPI routers, split by bounded context.

Each router owns one slice of the frontend contract and depends only on the
:class:`~medexa.api.dependencies.ServiceContainer` and the pure mappers, never
on AWS or concrete providers.
"""
