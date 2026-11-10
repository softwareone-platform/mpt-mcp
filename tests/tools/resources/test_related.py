from mpt_mcp.tools.resources.related import find_related_resources


def test_finds_children(products_registry):
    resource = "catalog.products"

    result = find_related_resources(resource, products_registry[resource], products_registry)

    assert [child.resource for child in result.children] == [
        "catalog.products.by_id",
        "catalog.products.by_id.items",
        "catalog.products.search",
    ]


def test_finds_similar(products_registry):
    resource = "catalog.products.by_id"

    result = find_related_resources(resource, products_registry[resource], products_registry)

    assert result.model_dump()["similar"] == [
        {"resource": "catalog.products.search", "summary": "Search products"}
    ]


def test_finds_closest_parent(products_registry):
    resource = "catalog.products.by_id.items"

    result = find_related_resources(resource, products_registry[resource], products_registry)

    assert result.model_dump()["parent"] == {
        "resource": "catalog.products.by_id",
        "summary": "Product by ID",
        "path": "/public/v1/catalog/products/{id}",
    }


def test_without_related_resources(products_registry):
    resource = "catalog.items"

    result = find_related_resources(resource, products_registry[resource], products_registry)

    assert result is None
