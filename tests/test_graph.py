from __future__ import annotations

import sqlite3

from coding_agent.rag.graph import CodeGraph, extract_calls, extract_imports, extract_inheritance
from coding_agent.types import EdgeType, GraphEdge

# ── Fixtures ─────────────────────────────────────────────


def _make_graph() -> tuple[sqlite3.Connection, CodeGraph]:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE chunks (id INTEGER PRIMARY KEY, file_path TEXT, "
        "line_start INTEGER, line_end INTEGER, content TEXT, "
        "symbol_name TEXT, symbol_kind TEXT)"
    )
    graph = CodeGraph(conn)
    return conn, graph


def _insert_chunk(conn: sqlite3.Connection, cid: int, file_path: str, symbol: str) -> None:
    conn.execute(
        "INSERT INTO chunks (id, file_path, line_start, line_end, content, symbol_name) "
        "VALUES (?, ?, 1, 10, 'content', ?)",
        (cid, file_path, symbol),
    )
    conn.commit()


# ── CodeGraph tests ──────────────────────────────────────


def test_create_table():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE chunks (id INTEGER PRIMARY KEY, file_path TEXT, "
        "line_start INTEGER, line_end INTEGER, content TEXT, "
        "symbol_name TEXT, symbol_kind TEXT)"
    )
    CodeGraph(conn)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    assert ("graph_edges",) in tables


def test_insert_edges():
    conn, graph = _make_graph()
    _insert_chunk(conn, 1, "main.py", "main")
    edges = [
        GraphEdge(source_chunk_id=1, target_name="helper", target_file="helper.py", edge_type=EdgeType.CALLS, line_number=5),
        GraphEdge(source_chunk_id=1, target_name="os", target_file="", edge_type=EdgeType.IMPORTS, line_number=1),
    ]
    graph.insert_edges(1, edges)
    rows = conn.execute("SELECT * FROM graph_edges").fetchall()
    assert len(rows) == 2


def test_insert_edges_empty():
    conn, graph = _make_graph()
    graph.insert_edges(1, [])
    rows = conn.execute("SELECT * FROM graph_edges").fetchall()
    assert len(rows) == 0


def test_remove_file_edges():
    conn, graph = _make_graph()
    _insert_chunk(conn, 1, "main.py", "main")
    _insert_chunk(conn, 2, "utils.py", "utils")
    graph.insert_edges(1, [
        GraphEdge(source_chunk_id=1, target_name="helper", target_file="", edge_type=EdgeType.CALLS, line_number=5),
    ])
    graph.insert_edges(2, [
        GraphEdge(source_chunk_id=2, target_name="os", target_file="", edge_type=EdgeType.IMPORTS, line_number=1),
    ])
    graph.remove_file_edges("main.py")
    remaining = conn.execute("SELECT * FROM graph_edges").fetchall()
    assert len(remaining) == 1
    assert remaining[0][1] == 2  # source_chunk_id for utils.py edge


def test_bfs_expand_no_seeds():
    conn, graph = _make_graph()
    result = graph.bfs_expand([])
    assert result == []


def test_bfs_expand_single_hop():
    conn, graph = _make_graph()
    _insert_chunk(conn, 1, "a.py", "func_a")
    _insert_chunk(conn, 2, "b.py", "func_b")
    graph.insert_edges(1, [
        GraphEdge(source_chunk_id=1, target_name="func_b", target_file="", edge_type=EdgeType.CALLS, line_number=3),
    ])
    _insert_chunk(conn, 3, "c.py", "func_c")
    result = graph.bfs_expand([1], max_depth=1, max_results=10)
    assert 2 in result
    assert 1 in result  # seeds are included


def test_bfs_expand_respects_max_depth():
    conn, graph = _make_graph()
    _insert_chunk(conn, 1, "a.py", "a")
    _insert_chunk(conn, 2, "b.py", "b")
    _insert_chunk(conn, 3, "c.py", "c")
    _insert_chunk(conn, 4, "d.py", "d")
    graph.insert_edges(1, [
        GraphEdge(source_chunk_id=1, target_name="b", target_file="", edge_type=EdgeType.CALLS, line_number=1),
    ])
    graph.insert_edges(2, [
        GraphEdge(source_chunk_id=2, target_name="c", target_file="", edge_type=EdgeType.CALLS, line_number=1),
    ])
    graph.insert_edges(3, [
        GraphEdge(source_chunk_id=3, target_name="d", target_file="", edge_type=EdgeType.CALLS, line_number=1),
    ])
    result = graph.bfs_expand([1], max_depth=1, max_results=10)
    assert 2 in result
    assert 3 not in result


def test_bfs_expand_respects_max_results():
    conn, graph = _make_graph()
    for i in range(1, 6):
        _insert_chunk(conn, i, f"{i}.py", f"func_{i}")
        graph.insert_edges(1, [
            GraphEdge(source_chunk_id=1, target_name=f"func_{i}", target_file="", edge_type=EdgeType.CALLS, line_number=i),
        ])
    result = graph.bfs_expand([1], max_depth=1, max_results=3)
    assert len(result) <= 3


def test_bfs_expand_edge_type_filter():
    conn, graph = _make_graph()
    _insert_chunk(conn, 1, "a.py", "a")
    _insert_chunk(conn, 2, "b.py", "b")
    _insert_chunk(conn, 3, "c.py", "c")
    graph.insert_edges(1, [
        GraphEdge(source_chunk_id=1, target_name="b", target_file="", edge_type=EdgeType.CALLS, line_number=1),
        GraphEdge(source_chunk_id=1, target_name="c", target_file="", edge_type=EdgeType.IMPORTS, line_number=2),
    ])
    result = graph.bfs_expand([1], max_depth=1, max_results=10, edge_types=[EdgeType.IMPORTS])
    assert 3 in result
    assert 2 not in result


def test_get_chunk_ids_for_target():
    conn, graph = _make_graph()
    _insert_chunk(conn, 1, "a.py", "a")
    graph.insert_edges(1, [
        GraphEdge(source_chunk_id=1, target_name="helper", target_file="", edge_type=EdgeType.CALLS, line_number=5),
    ])
    ids = graph.get_chunk_ids_for_target("helper")
    assert 1 in ids


def test_get_chunk_ids_for_target_with_type():
    conn, graph = _make_graph()
    _insert_chunk(conn, 1, "a.py", "a")
    graph.insert_edges(1, [
        GraphEdge(source_chunk_id=1, target_name="helper", target_file="", edge_type=EdgeType.CALLS, line_number=5),
    ])
    ids = graph.get_chunk_ids_for_target("helper", EdgeType.IMPORTS)
    assert ids == []


# ── Edge extraction tests ────────────────────────────────


def test_extract_calls_simple():
    content = "result = process(data)"
    calls = extract_calls(content)
    assert "process" in calls


def test_extract_calls_keywords_filtered():
    content = "if x > 0: return True"
    calls = extract_calls(content)
    assert "if" not in calls
    assert "return" not in calls


def test_extract_calls_no_matches():
    content = "# just a comment"
    calls = extract_calls(content)
    assert calls == []


def test_extract_calls_multiple():
    content = "a = foo(x)\nb = bar(y)\nc = baz(z)"
    calls = extract_calls(content)
    assert "foo" in calls
    assert "bar" in calls
    assert "baz" in calls


def test_extract_imports_python():
    content = "import os\nfrom pathlib import Path"
    imports = extract_imports(content, language="python")
    assert ("", "os") in imports
    assert ("pathlib", "Path") in imports


def test_extract_imports_ts():
    content = "import { readFile } from 'fs'\nimport path from 'path'"
    imports = extract_imports(content, language="typescript")
    assert len(imports) >= 2


def test_extract_imports_unknown_language():
    content = "import os"
    imports = extract_imports(content, language="rust")
    assert imports == []


def test_extract_inheritance_single():
    content = "class Dog(Mammal):"
    parents = extract_inheritance(content)
    assert "Mammal" in parents


def test_extract_inheritance_multiple():
    content = "class Dog(Mammal, Pet):"
    parents = extract_inheritance(content)
    assert "Mammal" in parents
    assert "Pet" in parents


def test_extract_inheritance_no_match():
    content = "class Dog:"
    parents = extract_inheritance(content)
    assert parents == []


def test_extract_inheritance_skips_object():
    content = "class Dog(object):"
    parents = extract_inheritance(content)
    assert "object" not in parents
