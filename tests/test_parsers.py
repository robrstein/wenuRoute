"""Tests for WenuRoute parsers and core models."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from wenuroute.models import NodeKind, RouteEdge, RouteGraph, RouteNode


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestRouteGraph:
    def test_add_node(self):
        g = RouteGraph()
        n = RouteNode(id="a", label="A", kind=NodeKind.FUNCTION)
        g.add_node(n)
        assert "a" in g.nodes

    def test_add_edge_no_duplicates(self):
        g = RouteGraph()
        e = RouteEdge("a", "b", "calls")
        g.add_edge(e)
        g.add_edge(e)
        assert g.edges.count(e) == 1

    def test_merge(self):
        g1 = RouteGraph()
        g1.add_node(RouteNode(id="x", label="X"))
        g2 = RouteGraph()
        g2.add_node(RouteNode(id="y", label="Y"))
        g2.add_edge(RouteEdge("x", "y"))
        g1.merge(g2)
        assert "y" in g1.nodes
        assert len(g1.edges) == 1


# ---------------------------------------------------------------------------
# HTML parser
# ---------------------------------------------------------------------------

class TestHtmlParser:
    def _parser(self, tmp_path: Path):
        from wenuroute.parsers.html import HtmlParser
        return HtmlParser(tmp_path)

    def test_detects_button(self, tmp_path):
        html = tmp_path / "index.html"
        html.write_text(
            "<html><body><button onclick=\"doSomething()\">Click</button></body></html>"
        )
        parser = self._parser(tmp_path)
        graph = parser.parse(html)
        kinds = {n.kind for n in graph.nodes.values()}
        assert NodeKind.UI_ELEMENT in kinds

    def test_detects_form_endpoint(self, tmp_path):
        html = tmp_path / "form.html"
        html.write_text(
            '<html><body><form action="/submit" method="POST"><input type="submit"></form></body></html>'
        )
        parser = self._parser(tmp_path)
        graph = parser.parse(html)
        ep_nodes = [n for n in graph.nodes.values() if n.kind == NodeKind.ENDPOINT]
        assert any("/submit" in n.label for n in ep_nodes)

    def test_detects_stylesheet(self, tmp_path):
        html = tmp_path / "page.html"
        html.write_text(
            '<html><head><link rel="stylesheet" href="styles.css"></head><body></body></html>'
        )
        parser = self._parser(tmp_path)
        graph = parser.parse(html)
        style_nodes = [n for n in graph.nodes.values() if n.kind == NodeKind.STYLE]
        assert style_nodes

    def test_detects_event_handler_function(self, tmp_path):
        html = tmp_path / "btn.html"
        html.write_text(
            '<html><body><button onclick="handleClick(event)">Go</button></body></html>'
        )
        parser = self._parser(tmp_path)
        graph = parser.parse(html)
        fn_nodes = [n for n in graph.nodes.values() if n.kind == NodeKind.FUNCTION]
        assert any("handleClick" in n.label for n in fn_nodes)


# ---------------------------------------------------------------------------
# React / JS parser
# ---------------------------------------------------------------------------

class TestReactParser:
    def _parser(self, tmp_path: Path):
        from wenuroute.parsers.react import ReactParser
        return ReactParser(tmp_path)

    def test_detects_function(self, tmp_path):
        js = tmp_path / "app.js"
        js.write_text("function greet(name, age) { return name; }")
        parser = self._parser(tmp_path)
        graph = parser.parse(js)
        fn_nodes = [n for n in graph.nodes.values() if n.kind == NodeKind.FUNCTION]
        assert any("greet" in n.label for n in fn_nodes)
        greet = next(n for n in fn_nodes if "greet" in n.label)
        assert "name" in greet.params
        assert "age" in greet.params

    def test_detects_fetch_endpoint(self, tmp_path):
        js = tmp_path / "api.js"
        js.write_text("fetch('/api/users').then(r => r.json())")
        parser = self._parser(tmp_path)
        graph = parser.parse(js)
        ep_nodes = [n for n in graph.nodes.values() if n.kind == NodeKind.ENDPOINT]
        assert any("/api/users" in n.label for n in ep_nodes)

    def test_detects_axios_endpoint(self, tmp_path):
        js = tmp_path / "service.js"
        js.write_text("axios.post('/api/login', payload)")
        parser = self._parser(tmp_path)
        graph = parser.parse(js)
        ep_nodes = [n for n in graph.nodes.values() if n.kind == NodeKind.ENDPOINT]
        assert any("POST" in n.label and "/api/login" in n.label for n in ep_nodes)

    def test_detects_jsx_event(self, tmp_path):
        jsx = tmp_path / "Button.jsx"
        jsx.write_text("const B = () => <button onClick={handleClick}>OK</button>")
        parser = self._parser(tmp_path)
        graph = parser.parse(jsx)
        ev_nodes = [n for n in graph.nodes.values() if n.kind == NodeKind.EVENT]
        assert ev_nodes


# ---------------------------------------------------------------------------
# Python parser
# ---------------------------------------------------------------------------

class TestPythonParser:
    def _parser(self, tmp_path: Path):
        from wenuroute.parsers.python import PythonParser
        return PythonParser(tmp_path)

    def test_detects_function(self, tmp_path):
        src = tmp_path / "views.py"
        src.write_text("def get_user(user_id, db):\n    pass\n")
        parser = self._parser(tmp_path)
        graph = parser.parse(src)
        fn_nodes = [n for n in graph.nodes.values() if n.kind == NodeKind.FUNCTION]
        assert any("get_user" in n.label for n in fn_nodes)
        fn = next(n for n in fn_nodes if "get_user" in n.label)
        assert "user_id" in fn.params

    def test_detects_flask_route(self, tmp_path):
        src = tmp_path / "app.py"
        src.write_text(
            textwrap.dedent("""\
            from flask import Flask
            app = Flask(__name__)

            @app.route('/users', methods=['GET', 'POST'])
            def users():
                pass
            """)
        )
        parser = self._parser(tmp_path)
        graph = parser.parse(src)
        ep_nodes = [n for n in graph.nodes.values() if n.kind == NodeKind.ENDPOINT]
        assert any("/users" in n.label for n in ep_nodes)

    def test_detects_fastapi_route(self, tmp_path):
        src = tmp_path / "main.py"
        src.write_text(
            textwrap.dedent("""\
            from fastapi import FastAPI
            app = FastAPI()

            @app.get('/items/{item_id}')
            def read_item(item_id: int):
                pass
            """)
        )
        parser = self._parser(tmp_path)
        graph = parser.parse(src)
        ep_nodes = [n for n in graph.nodes.values() if n.kind == NodeKind.ENDPOINT]
        assert any("/items" in n.label for n in ep_nodes)

    def test_detects_sql_raw(self, tmp_path):
        src = tmp_path / "db.py"
        src.write_text(
            "cursor.execute('SELECT * FROM users WHERE id = %s', (uid,))\n"
        )
        parser = self._parser(tmp_path)
        graph = parser.parse(src)
        sql_nodes = [n for n in graph.nodes.values() if n.kind == NodeKind.SQL]
        assert sql_nodes


# ---------------------------------------------------------------------------
# Node.js parser
# ---------------------------------------------------------------------------

class TestNodejsParser:
    def _parser(self, tmp_path: Path):
        from wenuroute.parsers.nodejs import NodejsParser
        return NodejsParser(tmp_path)

    def test_detects_express_route(self, tmp_path):
        js = tmp_path / "routes.js"
        js.write_text("app.get('/health', (req, res) => res.send('ok'))")
        parser = self._parser(tmp_path)
        graph = parser.parse(js)
        ep_nodes = [n for n in graph.nodes.values() if n.kind == NodeKind.ENDPOINT]
        assert any("GET" in n.label and "/health" in n.label for n in ep_nodes)


# ---------------------------------------------------------------------------
# Flutter parser
# ---------------------------------------------------------------------------

class TestFlutterParser:
    def _parser(self, tmp_path: Path):
        from wenuroute.parsers.flutter import FlutterParser
        return FlutterParser(tmp_path)

    def test_detects_widget(self, tmp_path):
        dart = tmp_path / "main.dart"
        dart.write_text(
            textwrap.dedent("""\
            class MyButton extends StatelessWidget {
              Widget build(BuildContext context) {
                return ElevatedButton(
                  onPressed: () {
                    doSomething();
                  },
                  child: Text('Press'),
                );
              }
            }
            """)
        )
        parser = self._parser(tmp_path)
        graph = parser.parse(dart)
        ui_nodes = [n for n in graph.nodes.values() if n.kind == NodeKind.UI_ELEMENT]
        assert any("MyButton" in n.label for n in ui_nodes)

    def test_detects_http_call(self, tmp_path):
        dart = tmp_path / "service.dart"
        dart.write_text("final response = await http.get('https://api.example.com/data');")
        parser = self._parser(tmp_path)
        graph = parser.parse(dart)
        ep_nodes = [n for n in graph.nodes.values() if n.kind == NodeKind.ENDPOINT]
        assert ep_nodes


# ---------------------------------------------------------------------------
# Android parser
# ---------------------------------------------------------------------------

class TestAndroidParser:
    def _parser(self, tmp_path: Path):
        from wenuroute.parsers.android import AndroidParser
        return AndroidParser(tmp_path)

    def test_detects_activity(self, tmp_path):
        java = tmp_path / "MainActivity.java"
        java.write_text(
            textwrap.dedent("""\
            public class MainActivity extends AppCompatActivity {
                @Override
                public void onCreate(Bundle savedInstanceState) {
                    super.onCreate(savedInstanceState);
                }
            }
            """)
        )
        parser = self._parser(tmp_path)
        graph = parser.parse(java)
        assert "MainActivity" in {n.label for n in graph.nodes.values()}

    def test_detects_retrofit_route(self, tmp_path):
        java = tmp_path / "ApiService.java"
        java.write_text(
            textwrap.dedent("""\
            public interface ApiService {
                @GET("/users/{id}")
                Call<User> getUser(@Path("id") int id);
            }
            """)
        )
        parser = self._parser(tmp_path)
        graph = parser.parse(java)
        ep_nodes = [n for n in graph.nodes.values() if n.kind == NodeKind.ENDPOINT]
        assert any("/users" in n.label for n in ep_nodes)
