import pytest

from mpt_mcp.tools.query.params import build_query

QUERY_LIMIT = 50
QUERY_OFFSET = 20
AUDIT_RQL = 'gt(audit.created.at,"2026-01-22T00:00:00Z")'
DATE_RANGE_RQL = (
    'and(gt(audit.created.at,"2026-01-22T00:00:00Z"),lt(audit.created.at,"2026-01-22T23:59:59Z"))'
)


@pytest.fixture
def built_query(endpoints_registry, query_params_factory, spec_factory):
    def factory(resource="commerce.orders", openapi_spec=None, **query_args):
        query, _ = build_query(
            resource,
            endpoints_registry[resource]["path"],
            query_params_factory(**query_args),
            spec_factory(openapi_spec=openapi_spec),
        )
        return query.to_query()

    return factory


@pytest.fixture
def built_select(built_query):
    def factory(**query_args):
        select = built_query(**query_args).get("select", "")
        return [part.lstrip("+") for part in select.split(",")] if select else []

    return factory


@pytest.mark.parametrize(
    ("rql", "order"),
    [
        ('gt(audit.created.at,"2026-01-22T00:00:00Z")', None),
        ('lt(audit.updated.at,"2026-01-22T23:59:59Z")', None),
        ('ge(audit.completed.at,"2026-01-22T00:00:00Z")', None),
        ('eq(audit.processing.at,"2026-01-22T10:00:00Z")', None),
        ('lte(audit.quoted.at,"2026-01-22T23:59:59Z")', None),
        ('ge(audit.failed.at,"2026-01-22T00:00:00Z")', None),
        ('eq(audit.created.by.id,"USR-123")', None),
        ("", "-audit.created.at"),
        ("", "+audit.updated.at"),
        (DATE_RANGE_RQL, "-audit.created.at"),
    ],
)
def test_adds_audit_to_select_for_audit_fields(built_select, rql, order):
    result = built_select(rql=rql, order=order)

    assert any(part.startswith("audit.") for part in result)


@pytest.mark.parametrize("select", ["audit,+id,+name", "+audit,+id,+name"])
def test_keeps_single_audit_in_select(built_select, select):
    result = built_select(rql=AUDIT_RQL, select=select)

    assert result.count("audit") == 1


def test_skips_audit_with_dot_notation(built_select):
    result = built_select(rql=AUDIT_RQL, select="+audit.created.at,+id,+name")

    assert "audit.created.at" in result
    assert "audit" not in result


def test_skips_audit_without_audit_fields(built_select):
    result = built_select(rql='eq(status,"Completed")', order="-status")

    assert "audit" not in result


def test_appends_audit_to_existing_select(built_select):
    result = built_select(rql=AUDIT_RQL, select="+id,+name,+status")

    assert {"audit.created.at", "id", "name", "status"} <= set(result)


def test_creates_audit_select_without_select(built_query):
    result = built_query(rql=AUDIT_RQL)

    assert result["select"] == "id,+audit.created.at"


def test_adds_used_audit_fields_with_exclude_all(built_select):
    result = built_select(
        rql=AUDIT_RQL, select="-*,+id,+status", order="-audit.updated.at,-audit.created.at"
    )

    assert result == ["-*", "id", "status", "audit.created.at", "audit.updated.at"]


def test_adds_used_audit_fields_to_default(built_select):
    result = built_select(rql=AUDIT_RQL, select="+id,+status")

    assert result == ["id", "status", "audit.created.at"]


def test_real_world_date_range_query(built_query):
    result = built_query(
        rql=DATE_RANGE_RQL,
        limit=100,
        select="+id,+product.id,+product.name",
        order="-audit.created.at",
    )

    select_fields = {part.lstrip("+") for part in result["select"].split(",")}
    assert {"audit.created.at", "id", "product.id", "product.name"} <= select_fields
    assert result["order"] == "-audit.created.at"


def test_real_world_recent_orders_query(built_select):
    result = built_select(
        limit=QUERY_LIMIT, select="+id,+status,+product.name", order="-audit.created.at"
    )

    assert {"audit.created.at", "id", "status", "product.name"} <= set(result)


def test_removes_spaces_after_rql_commas(built_query):
    result = built_query(rql="and(eq(status,Active), ilike(name,*Microsoft*))")

    assert result["rql"] == "and(eq(status,Active),ilike(name,*Microsoft*))"


@pytest.mark.parametrize("limit", [QUERY_LIMIT, 0])
def test_sends_limit(built_query, limit):
    result = built_query(resource="catalog.products", limit=limit)

    assert result["limit"] == limit


def test_catalog_products_default_select(built_query):
    result = built_query(resource="catalog.products")

    assert result["select"] == "-*,+id,+name,+shortDescription"


def test_sanitizes_select_drops_invalid_adds_id(built_select, openapi_spec):
    result = built_select(select="audit,status,orderNumber", openapi_spec=openapi_spec)

    assert {"id", "audit", "status"} <= set(result)
    assert "orderNumber" not in result


def test_select_without_openapi_spec_adds_id(built_select):
    result = built_select(select="audit,status")

    assert {"id", "audit", "status"} <= set(result)


@pytest.mark.parametrize(
    ("select", "fields", "expected"),
    [
        (None, None, None),
        ("", ["id", "audit", "status"], None),
        ("  ", ["id", "audit", "status"], "  "),
        ("audit,status", None, "id,status,audit"),
        ("audit,status", ["id", "audit", "status"], "id,status,audit"),
        ("id,audit,status", ["id", "audit", "status"], "id,status,audit"),
        ("audit,status,orderNumber", ["id", "audit", "status"], "id,status,audit"),
        ("+audit,+status", ["id", "audit", "status"], "id,status,+audit"),
        ("audit.created.at,status", ["id", "audit", "status"], "id,status,audit.created.at"),
        ("audit", ["id", "status", "name", "audit"], "id,status,name,audit"),
        ("id,audit", ["id", "status", "name", "audit"], "id,status,name,audit"),
    ],
)
def test_sanitizes_select_against_schema(
    built_query, openapi_spec_factory, select, fields, expected
):
    openapi_spec = None if fields is None else openapi_spec_factory(fields)

    result = built_query(select=select, openapi_spec=openapi_spec)

    assert result.get("select") == expected


@pytest.mark.parametrize(
    ("endpoint_path", "expected"),
    [
        ("/public/v1/commerce/orders/{id}", {}),
        ("/public/v1/commerce/orders/{orderId}/lines", {"limit": 10, "offset": QUERY_OFFSET}),
    ],
)
def test_pages_only_collections(query_params_factory, spec_factory, endpoint_path, expected):
    requested = query_params_factory(offset=QUERY_OFFSET)

    result = build_query("commerce.orders", endpoint_path, requested, spec_factory())

    query_params = result[0].to_query()
    assert {key: query_params[key] for key in ("limit", "offset") if key in query_params} == (
        expected
    )


def test_fallback_query_keeps_requested_select(query_params_factory, spec_factory):
    requested = query_params_factory(rql=AUDIT_RQL, select="+id,+name")

    result = build_query("commerce.orders", "/public/v1/commerce/orders", requested, spec_factory())

    fallback_query = result[1]
    assert fallback_query is not None
    assert fallback_query.select == "+id,+name"


def test_no_fallback_query_without_added_audit(query_params_factory, spec_factory):
    requested = query_params_factory(rql="eq(status,Active)")

    result = build_query("commerce.orders", "/public/v1/commerce/orders", requested, spec_factory())

    assert result[1] is None
