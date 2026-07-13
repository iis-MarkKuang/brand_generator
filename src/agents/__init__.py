"""StyleForge agents — one module per agent (Brand Analyst, Art Director, ...).

Agents are tools called by the Art Director's tool-calling loop (CP-008), but each
is exposed as a standalone async function so it can be tested in isolation.
"""
