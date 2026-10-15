import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from contractlens import ContractError, compare, render_html


def spec():
    return {'openapi': '3.0.3', 'paths': {'/pets': {'get': {'responses': {'200': {'description': 'ok', 'content': {'application/json': {'schema': {'type': 'object', 'required': ['id'], 'properties': {'id': {'type': 'integer'}}}}}}}}}}}


def response(s):
    return s['paths']['/pets']['get']['responses']['200']['content']['application/json']['schema']


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.a = spec()
        self.b = copy.deepcopy(self.a)

    def codes(self):
        return {f.code for f in compare(self.a, self.b)}

    def test_identical(self):
        self.assertEqual(compare(self.a, self.b), [])

    def test_path_removed(self):
        self.b['paths'] = {}
        self.assertIn('path.removed', self.codes())

    def test_operation_removed(self):
        self.b['paths']['/pets'] = {}
        self.assertIn('operation.removed', self.codes())

    def test_response_required_removed(self):
        response(self.b)['required'] = []
        self.assertIn('schema.required', self.codes())

    def test_response_property_removed(self):
        response(self.b)['properties'] = {}
        self.assertIn('schema.property.removed', self.codes())

    def test_response_type(self):
        response(self.b)['properties']['id']['type'] = 'string'
        self.assertIn('schema.type', self.codes())

    def test_add_optional_response(self):
        response(self.b)['properties']['name'] = {'type': 'string'}
        self.assertEqual(compare(self.a, self.b), [])

    def test_parameter_required(self):
        self.b['paths']['/pets']['get']['parameters'] = [{'in': 'query', 'name': 'page', 'required': True, 'schema': {'type': 'integer'}}]
        self.assertIn('parameter.required', self.codes())

    def test_path_parameter_inheritance_and_override(self):
        p = {'in': 'query', 'name': 'q', 'required': False, 'schema': {'type': 'string'}}
        for s in (self.a, self.b):
            s['paths']['/pets']['parameters'] = [copy.deepcopy(p)]
        self.b['paths']['/pets']['get']['parameters'] = [{**p, 'required': True}]
        self.assertIn('parameter.required', self.codes())

    def test_enum_directions(self):
        for direction in ('request', 'response'):
            for widening in (True, False):
                a, b = spec(), spec()
                sa, sb = ({'type': 'string', 'enum': ['a']}, {'type': 'string', 'enum': ['a', 'b']})
                if not widening:
                    sa, sb = sb, sa
                if direction == 'response':
                    response(a).update(sa)
                    response(b).update(sb)
                else:
                    for s, v in ((a, sa), (b, sb)):
                        s['paths']['/pets']['get']['parameters'] = [{'in': 'query', 'name': 'q', 'schema': v}]
                f = next(f for f in compare(a, b) if f.code == 'schema.enum')
                self.assertEqual(f.severity, 'breaking' if widening == (direction == 'response') else 'info')

    def test_ref_target_change(self):
        for s in (self.a, self.b):
            response(s)['properties']['id'] = {'$ref': '#/components/schemas/Id'}
            s['components'] = {'schemas': {'Id': {'type': 'integer'}}}
        self.b['components']['schemas']['Id']['type'] = 'string'
        self.assertIn('schema.type', self.codes())

    def test_external_reference_rejected(self):
        response(self.b)['properties']['id'] = {'$ref': 'https://example.com/schema'}
        with self.assertRaises(ContractError):
            compare(self.a, self.b)

    def test_cyclic_reference_rejected(self):
        self.b['paths']['/pets'] = {'$ref': '#/paths/~1pets'}
        with self.assertRaises(ContractError):
            compare(self.a, self.b)

    def test_constraint_review(self):
        response(self.b)['minProperties'] = 1
        self.assertIn('schema.constraint', self.codes())

    def test_security_change(self):
        self.b['security'] = [{'token': []}]
        self.assertIn('operation.security', self.codes())

    def test_html_escapes(self):
        from contractlens import Finding
        report = render_html([Finding('review', 'test', '<script>', 'A & B')])
        self.assertNotIn('<script>', report)
        self.assertIn('&lt;script&gt;', report)
        self.assertIn('A &amp; B', report)

    def test_invalid_version(self):
        self.b['openapi'] = '2.0'
        with self.assertRaises(ContractError):
            compare(self.a, self.b)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            a, b, out = (Path(d) / n for n in ('a.json', 'b.json', 'report.html'))
            a.write_text(json.dumps(self.a))
            self.b['paths'] = {}
            b.write_text(json.dumps(self.b))
            command = [sys.executable, '-m', 'contractlens', str(a), str(b)]
            run = subprocess.run(command + ['--format', 'json'], capture_output=True, text=True)
            self.assertEqual(run.returncode, 1)
            self.assertEqual(json.loads(run.stdout)['findings'][0]['code'], 'path.removed')
            run = subprocess.run(command + ['--format', 'html', '--output', str(out), '--fail-on', 'never'], capture_output=True)
            self.assertEqual(run.returncode, 0)
            self.assertIn('<!doctype html>', out.read_text())
            b.write_text('broken')
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)


if __name__ == '__main__':
    unittest.main()
