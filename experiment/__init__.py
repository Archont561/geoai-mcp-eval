"""geoai-mcp-eval — the experiment source root for the thesis.

The study compares, on one pinned model and one pinned engine, exposing nine
geoprocessing operations to the model as typed MCP tools versus asking the same
model to generate and run PyQGIS code, holding engine, data and oracle constant,
scored on executed spatial artefacts.

The experiment design is deliberately NOT pinned in this scaffold:
do not presuppose module layout (backends / tasks / oracles will be decided
when the design is final).
"""

__version__ = "0.1.0"
