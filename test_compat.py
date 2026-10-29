"""A TV LG de 2021 (webOS 6) abre o player num Chrome 79: JS e CSS não podem passar disso.

Sintaxe que o 79 não conhece derruba o módulo inteiro (a página abre sem nenhuma lista), e um
seletor desconhecido num grupo derruba a regra toda. Estas verificações pegam o que já mordeu.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
JS_FILES = sorted((ROOT / "static" / "js").glob("*.js"))
CSS = (ROOT / "static" / "app.css").read_text()

# Chrome 80: ?. e ??   Chrome 85: ||= &&= ??=
JS_SYNTAX = {
    "?.": re.compile(r"\?\.(?!\d)"),
    "??": re.compile(r"\?\?"),
    "||= / &&=": re.compile(r"(\|\||&&)="),
}


def css_rules(css):
    """(seletor, corpo) de cada regra; os blocos @media/@supports entram pelas regras de dentro."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}@;]+)\{([^{}]*)\}", css)]


class ChromeCompatTest(unittest.TestCase):
    def test_js_has_no_syntax_newer_than_chrome_79(self):
        for path in JS_FILES:
            for n, line in enumerate(path.read_text().splitlines(), 1):
                for name, pattern in JS_SYNTAX.items():
                    with self.subTest(file=path.name, line=n):
                        self.assertNotRegex(line, pattern, f"{name} em {path.name}:{n}")

    def test_js_avoids_apis_newer_than_chrome_79(self):
        # URLSearchParams.size: Chrome 113 (no 79 vem undefined e os links de categoria perdem o ?g=)
        for path in JS_FILES:
            src = path.read_text()
            for name in set(re.findall(r"(\w+)\s*=\s*new URLSearchParams\(", src)):
                with self.subTest(file=path.name, var=name):
                    self.assertIsNone(re.search(rf"\b{name}\.size\b", src), f"{name}.size em {path.name}")
            for api in (".at(", ".replaceAll(", "structuredClone(", ".findLast(", "Object.hasOwn(", ".replaceChildren("):
                with self.subTest(file=path.name, api=api):
                    self.assertNotIn(api, src, f"{api} em {path.name}")

    def test_css_avoids_properties_chrome_79_ignores(self):
        # inset: Chrome 87; translate/scale/rotate soltos: 104; :has(): 105
        for pattern in (r"(?<![\w-])inset\s*:", r"(?<![\w-])(translate|scale|rotate)\s*:", r":has\("):
            with self.subTest(pattern=pattern):
                self.assertNotRegex(CSS, pattern)

    def test_focus_visible_never_shares_a_rule(self):
        for selector, _ in css_rules(CSS):
            if ":focus-visible" in selector:
                self.assertNotIn(",", selector, f"'{selector}' seria descartada inteira no Chrome 79")

    def test_dvh_comes_after_a_vh_fallback(self):
        for selector, body in css_rules(CSS):
            decls = [d.strip() for d in body.split(";") if d.strip()]
            for i, decl in enumerate(decls):
                if "dvh" in decl:
                    prop = decl.split(":")[0]
                    with self.subTest(selector=selector):
                        self.assertTrue(i > 0 and decls[i - 1].startswith(prop + ":") and "vh" in decls[i - 1],
                                        f"{selector}: '{decl}' sem '{prop}' em vh logo antes")

    def test_aspect_ratio_has_fallback(self):
        if "aspect-ratio:" in CSS:
            self.assertIn("@supports not (aspect-ratio", CSS)


if __name__ == "__main__":
    unittest.main()
