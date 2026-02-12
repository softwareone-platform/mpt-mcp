from typing import Any


def get_query_templates() -> dict[str, Any]:
    """
    Returns pre-built query templates organized by category.

    These templates help users quickly perform common tasks without
    learning RQL syntax from scratch.
    """
    return {
        "orders": {
            "description": "Common order queries",
            "templates": [
                {
                    "name": "Recent orders",
                    "description": "Get the most recently created orders",
                    "query": "marketplace_query(resource='commerce.orders', order='-audit.created.at', limit=20)",
                    "use_case": "Monitor new orders coming in",
                },
                {
                    "name": "Orders by status",
                    "description": "Filter orders by their current status",
                    "query": "marketplace_query(resource='commerce.orders', rql='eq(status,Querying)', limit=50)",
                    "available_statuses": ["Draft", "Querying", "Processing", "Completed", "Failed", "Cancelled"],
                    "use_case": "Track orders in a specific state",
                },
                {
                    "name": "Recent completed orders",
                    "description": "Get recently completed orders",
                    "query": "marketplace_query(resource='commerce.orders', rql='eq(status,Completed)', order='-audit.updated.at', limit=20)",
                    "use_case": "Review recently fulfilled orders",
                },
                {
                    "name": "Orders for specific product",
                    "description": "Find all orders containing a specific product",
                    "query": "marketplace_query(resource='commerce.orders', rql='eq(product.id,PRD-xxxx-xxxx)', limit=50)",
                    "use_case": "Track orders for a particular product",
                },
                {
                    "name": "Large orders",
                    "description": "Find orders above a certain value",
                    "query": "marketplace_query(resource='commerce.orders', rql='gt(price.PPxM,1000)', order='-price.PPxM', limit=20)",
                    "use_case": "Identify high-value orders",
                },
            ],
        },
        "products": {
            "description": "Common product queries",
            "templates": [
                {
                    "name": "Published products",
                    "description": "Get all published products",
                    "query": "marketplace_query(resource='catalog.products', rql='eq(status,Published)', limit=50)",
                    "available_statuses": ["Draft", "Published", "Unpublished"],
                    "use_case": "See what's currently available in the catalog",
                },
                {
                    "name": "Products by vendor",
                    "description": "Find all products from a specific vendor",
                    "query": "marketplace_query(resource='catalog.products', rql='eq(vendor.id,ACC-xxxx-xxxx)', limit=50)",
                    "use_case": "View a vendor's product catalog",
                },
                {
                    "name": "Search products by name",
                    "description": "Search for products containing specific keywords",
                    "query": "marketplace_query(resource='catalog.products', rql='ilike(name,*Microsoft*)', limit=50)",
                    "use_case": "Find products matching search terms",
                },
                {
                    "name": "Recently updated products",
                    "description": "Get products that were recently modified",
                    "query": "marketplace_query(resource='catalog.products', order='-audit.updated.at', limit=20)",
                    "use_case": "Monitor product catalog changes",
                },
                {
                    "name": "Products with items",
                    "description": "Find products that have available items",
                    "query": "marketplace_query(resource='catalog.products', rql='gt(statistics.itemCount,0)', limit=50)",
                    "use_case": "See products ready for ordering",
                },
            ],
        },
        "agreements": {
            "description": "Common agreement queries",
            "templates": [
                {
                    "name": "Active agreements",
                    "description": "Get all active agreements",
                    "query": "marketplace_query(resource='commerce.agreements', rql='eq(status,Active)', limit=50)",
                    "available_statuses": ["Draft", "Active", "Terminated"],
                    "use_case": "View current active agreements",
                },
                {
                    "name": "Agreements by client",
                    "description": "Find all agreements for a specific client",
                    "query": "marketplace_query(resource='commerce.agreements', rql='eq(client.id,ACC-xxxx-xxxx)', limit=50)",
                    "use_case": "Review a client's agreements",
                },
                {
                    "name": "Recent agreements",
                    "description": "Get recently created agreements",
                    "query": "marketplace_query(resource='commerce.agreements', order='-audit.created.at', limit=20)",
                    "use_case": "Monitor new agreements",
                },
            ],
        },
        "subscriptions": {
            "description": "Common subscription queries",
            "templates": [
                {
                    "name": "Active subscriptions",
                    "description": "Get all active subscriptions",
                    "query": "marketplace_query(resource='commerce.subscriptions', rql='eq(status,Active)', limit=50)",
                    "available_statuses": ["Active", "Updating", "Terminating", "Terminated"],
                    "use_case": "View current active subscriptions",
                },
                {
                    "name": "Subscriptions by product",
                    "description": "Find subscriptions for a specific product",
                    "query": "marketplace_query(resource='commerce.subscriptions', rql='eq(product.id,PRD-xxxx-xxxx)', limit=50)",
                    "use_case": "Track subscriptions for a product",
                },
                {
                    "name": "Expiring soon",
                    "description": "Find subscriptions ending in the next 30 days",
                    "query": "marketplace_query(resource='commerce.subscriptions', rql='and(eq(status,Active),lt(endDate,2024-12-31))', order='+endDate', limit=50)",
                    "use_case": "Proactive renewal management",
                },
            ],
        },
        "accounts": {
            "description": "Common account queries",
            "templates": [
                {
                    "name": "Active buyers",
                    "description": "Get all active buyer accounts",
                    "query": "marketplace_query(resource='accounts.buyers', rql='eq(status,Active)', limit=50)",
                    "available_statuses": ["Active", "Inactive"],
                    "use_case": "View active buyer accounts",
                },
                {
                    "name": "Search buyers by name",
                    "description": "Find buyers matching search terms",
                    "query": "marketplace_query(resource='accounts.buyers', rql='ilike(name,*Corp*)', limit=50)",
                    "use_case": "Locate specific buyer accounts",
                },
                {
                    "name": "Recent users",
                    "description": "Get recently created users",
                    "query": "marketplace_query(resource='accounts.users', order='-audit.created.at', limit=20)",
                    "use_case": "Monitor new user registrations",
                },
            ],
        },
        "tips": {
            "how_to_use": [
                "1. Copy the query from the template",
                "2. Replace placeholder values (xxxx-xxxx) with actual IDs",
                "3. Adjust limit parameter based on your needs",
                "4. Modify RQL filters to match your specific criteria",
            ],
            "rql_basics": {
                "equality": "eq(field,value) - Exact match",
                "search": "ilike(field,*keyword*) - Case-insensitive search",
                "comparison": "gt(field,value) - Greater than, lt(field,value) - Less than",
                "combine": "and(condition1,condition2) - Multiple conditions",
                "sorting": "order='-field' for descending, order='+field' for ascending",
            },
        },
    }
