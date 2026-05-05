# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#   "marimo>=0.13",
#   "numpy>=2.0",
# ]
# ///

import marimo

__generated_with = "0.23.5"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import numpy as np

    return mo, np


@app.cell
def _(mo):
    mo.md("""
    # uvloom marimo sandbox app
    """)
    return


@app.cell
def _(mo, np):
    xs = np.linspace(0, 2 * np.pi, 8)
    table = {"x": xs.round(3), "sin(x)": np.sin(xs).round(3)}
    mo.ui.table(table)
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
