'''Jinja2 template for the main file of ONE service.

It holds no endpoint code: it imports each endpoint's tool function from
<tool_name>.py in the same folder (see service_template.py), lists them in TOOLS and
registers them, so naming the service makes all its endpoints available.

Placeholders:
    service_name   identifier-safe service name, e.g. "demo_bistro"
    endpoints      list of endpoint dicts, each with tool_name and read_only
'''

SERVICE_TEMPLATE = '''from mcp.server.fastmcp import FastMCP

{% for e in endpoints -%}
from .{{ e.tool_name }} import {{ e.tool_name }}for{{ service_name }}
{% endfor %}
mcp = FastMCP("{{ service_name }}")

TOOLS = [
{%- for e in endpoints %}
    {{ e.tool_name }}for{{ service_name }},
{%- endfor %}
]

{% for e in endpoints -%}
mcp.tool(annotations={"readOnlyHint": {{ e.read_only }}})({{ e.tool_name }}for{{ service_name }})
{% endfor %}
if __name__ == "__main__":
    mcp.run()
'''
