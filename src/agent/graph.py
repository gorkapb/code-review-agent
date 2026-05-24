from langgraph.graph import END, START, StateGraph

from src.agent.nodes import analyze_diff, fetch_diff, format_output
from src.agent.state import ReviewState

builder = StateGraph(ReviewState)
builder.add_node(fetch_diff)
builder.add_node(analyze_diff)
builder.add_node(format_output)
builder.add_edge(START, "fetch_diff")
builder.add_edge("fetch_diff", "analyze_diff")
builder.add_edge("analyze_diff", "format_output")
builder.add_edge("format_output", END)

graph = builder.compile()
