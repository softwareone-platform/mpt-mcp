# Chat Check Prompt

Copy the prompt below into a new chat of an MCP client connected to the server (Claude Code, Claude Desktop, Cursor, VS Code Copilot) to check that the model can use every tool. It only reads data, and ends with a table of the steps that passed and failed.

[`smoke_test.py`](smoke_test.py) runs similar checks without a model. This prompt also checks what only a model shows: that the tool descriptions and the server instructions lead it to the right tool and arguments.

```text
Check the SoftwareOne Marketplace MCP server. Use only its tools, run every step in order, do not
stop at the first failure, and do not ask me anything. Keep each answer to one line.

1. Call marketplace_resources with search="order". Does commerce.orders appear?
2. Call marketplace_resources with category="catalog", then with category="catalog" and
   search="listing". Without search, either every resource has a path or the result has a note
   saying it was shortened; with search, does every resource have a path and no note?
3. Call marketplace_resource_info for catalog.products. Name two filterable fields and one example query.
4. Call marketplace_resource_schema for catalog.products. How many fields does it describe?
5. Call marketplace_audit_fields for commerce.orders. Which audit events does it have?
6. Count the products with marketplace_query and limit=0. What is the total?
7. List 5 products returning only id and name (select=-*,+id,+name). Do the items have only id,
   name and status?
8. Find products whose name contains "Microsoft" with an RQL filter. How many match?
9. Read the second page of 2 products using the next_offset of the first page. Are the IDs
   different from the first page?
10. Show the 3 most recently created orders, newest first. Do the items show audit.created.at?
11. Read the first product of step 7 by its ID with catalog.products.by_id. Is it the same product?
12. Call marketplace_query on catalog.products.by_id without path_params. Does it fail and say
    which path parameter is missing?
13. Call marketplace_query on catalog.products with limit=101. Does it fail validation?
14. Call marketplace_query on catalog.does_not_exist. Does it fail as an unknown resource?
15. Call marketplace_docs_index. How many pages and sections are there? If it says the
    documentation is not available, mark steps 15 to 17 as SKIP.
16. Search the documentation for "orders" with marketplace_docs_list. Give the title and the
    browser_url of the first page.
17. Read that page with marketplace_docs_read and summarize it in one sentence. Did you show me
    the browser_url and not the docs:// uri?

Finish with a table with the columns Step, Tool, Result (PASS, FAIL or SKIP) and Detail. A step
passes only when the tool answered as the question expects. For a FAIL, put the error message in
Detail.
```
