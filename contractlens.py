"""ContractLens: conservative OpenAPI JSON compatibility checks. Python 3.10+."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import html
import json
from pathlib import Path
import sys
from typing import Any

__version__ = '1.0.0'
METHODS = frozenset('get put post delete options head patch trace'.split())


class ContractError(ValueError):
    """Invalid or unsupported contract input."""


@dataclass(frozen=True, order=True)
class Finding:
    severity: str
    code: str
    location: str
    message: str


class Document:
    def __init__(self, data: dict[str, Any]):
        if not isinstance(data, dict) or not str(data.get('openapi', '')).startswith(('3.0.', '3.1.')):
            raise ContractError('Expected an OpenAPI 3.0 or 3.1 JSON object')
        if not isinstance(data.get('paths'), dict):
            raise ContractError('paths must be an object')
        self.data = data

    def resolve(self, value: Any, seen: frozenset[str] = frozenset()) -> Any:
        if not isinstance(value, dict):
            raise ContractError('Expected an object in contract')
        ref = value.get('$ref')
        if ref is None:
            return value
        if not isinstance(ref, str) or not ref.startswith('#/'):
            raise ContractError('Only local JSON pointer references are supported')
        if ref in seen:
            raise ContractError(f'Cyclic reference: {ref}')
        target: Any = self.data
        try:
            for part in ref[2:].split('/'):
                target = target[part.replace('~1', '/').replace('~0', '~')]
        except (KeyError, TypeError) as exc:
            raise ContractError(f'Unresolved reference: {ref}') from exc
        resolved = dict(self.resolve(target, seen | {ref}))
        # OpenAPI 3.0 Reference Object siblings are ignored.
        if self.data['openapi'].startswith('3.1.'):
            resolved.update({k: v for k, v in value.items() if k != '$ref'})
        return resolved


def compare(before: dict, after: dict) -> list[Finding]:
    """Compare the supported structural subset; unproven changes require review."""
    old, new = Document(before), Document(after)
    findings: list[Finding] = []

    def emit(severity: str, code: str, loc: str, message: str) -> None:
        findings.append(Finding(severity, code, loc, message))

    def schema(a: dict, b: dict, loc: str, direction: str, depth: int = 0) -> None:
        if depth > 64:
            raise ContractError('Schema nesting exceeds 64 levels')
        a, b = old.resolve(a), new.resolve(b)
        # Producer responses may narrow values; consumer requests may widen them.
        if a.get('type') != b.get('type'):
            emit('breaking', 'schema.type', loc, f"Type changed: {a.get('type')} → {b.get('type')}")
        if a.get('nullable', False) != b.get('nullable', False):
            breaking = (direction == 'request' and not b.get('nullable')) or (direction == 'response' and b.get('nullable'))
            emit('breaking' if breaking else 'info', 'schema.nullable', loc, 'Nullability changed')
        if 'enum' in a or 'enum' in b:
            # Use JSON serialization to support scalar and structured enum values.
            enumset = lambda v: {json.dumps(x, sort_keys=True) for x in v}
            av = enumset(a['enum']) if 'enum' in a else None
            bv = enumset(b['enum']) if 'enum' in b else None
            breaking = ((bv is not None and (av is None or not av <= bv)) if direction == 'request'
                        else (av is not None and (bv is None or not bv <= av)))
            if av != bv:
                emit('breaking' if breaking else 'info', 'schema.enum', loc, f'{direction.title()} allowed values changed')
        ar, br = set(a.get('required', [])), set(b.get('required', []))
        for name in sorted((br - ar) if direction == 'request' else (ar - br)):
            emit('breaking', 'schema.required', f'{loc}/{name}', 'Required request field added' if direction == 'request' else 'Response field no longer guaranteed')
        ap, bp = a.get('properties', {}), b.get('properties', {})
        for name in sorted(ap.keys() - bp.keys()):
            emit('review' if direction == 'request' else 'breaking', 'schema.property.removed', f'{loc}/{name}', 'Property removed')
        for name in sorted(ap.keys() & bp.keys()):
            schema(ap[name], bp[name], f'{loc}/{name}', direction, depth + 1)
        if 'items' in a and 'items' in b:
            schema(a['items'], b['items'], f'{loc}/items', direction, depth + 1)
        elif ('items' in a) != ('items' in b):
            emit('review', 'schema.items', loc, 'Array item constraint changed')
        handled = {'type', 'nullable', 'enum', 'required', 'properties', 'items', 'description', 'title', 'example', 'examples', 'deprecated'}
        for key in sorted((a.keys() | b.keys()) - handled):
            if a.get(key) != b.get(key):
                emit('review', 'schema.constraint', f'{loc}/{key}', 'Constraint changed; inspect compatibility manually')

    def content(a: dict, b: dict, loc: str, direction: str) -> None:
        ac, bc = a.get('content', {}), b.get('content', {})
        removed = ac.keys() - bc.keys() if direction == 'request' else bc.keys() - ac.keys()
        for media in sorted(removed):
            emit('breaking', 'media.changed', f'{loc}/{media}', 'Accepted request media removed' if direction == 'request' else 'New response media may surprise consumers')
        for media in sorted(ac.keys() & bc.keys()):
            sa, sb = ac[media].get('schema', {}), bc[media].get('schema', {})
            schema(sa, sb, f'{loc}/{media}', direction)

    def parameters(doc: Document, path: dict, op: dict) -> dict:
        result = {}
        for p in path.get('parameters', []) + op.get('parameters', []):
            p = doc.resolve(p)
            result[(p['in'], p['name'])] = p
        return result

    for path, raw in sorted(before['paths'].items()):
        if path.startswith('x-'):
            continue
        a = old.resolve(raw)
        if path not in after['paths']:
            emit('breaking', 'path.removed', path, 'Path removed')
            continue
        b = new.resolve(after['paths'][path])
        for method in sorted(a.keys() & METHODS):
            loc = f'{method.upper()} {path}'
            if method not in b:
                emit('breaking', 'operation.removed', loc, 'Operation removed')
                continue
            ao, bo = a[method], b[method]
            pa, pb = parameters(old, a, ao), parameters(new, b, bo)
            for key in sorted(pb.keys() - pa.keys()):
                if pb[key].get('required'):
                    emit('breaking', 'parameter.required', f'{loc}/{key[0]}/{key[1]}', 'Required parameter added')
            for key in sorted(pa.keys() - pb.keys()):
                emit('review', 'parameter.removed', f'{loc}/{key[0]}/{key[1]}', 'Parameter removed; server handling is unknown')
            for key in sorted(pa.keys() & pb.keys()):
                p, q = pa[key], pb[key]
                ploc = f'{loc}/{key[0]}/{key[1]}'
                if q.get('required') and not p.get('required'):
                    emit('breaking', 'parameter.required', ploc, 'Parameter became required')
                schema(p.get('schema', {}), q.get('schema', {}), ploc, 'request')
                for field in ('style', 'explode', 'allowReserved', 'content'):
                    if p.get(field) != q.get(field):
                        emit('review', 'parameter.serialization', ploc, f'{field} changed')
            ra, rb = old.resolve(ao.get('requestBody', {})), new.resolve(bo.get('requestBody', {}))
            if rb.get('required') and not ra.get('required'):
                emit('breaking', 'body.required', loc, 'Request body became required')
            content(ra, rb, f'{loc}/request', 'request')
            responses_a, responses_b = ao.get('responses', {}), bo.get('responses', {})
            for status in sorted(responses_a.keys() - responses_b.keys()):
                emit('breaking', 'response.removed', f'{loc}/{status}', 'Documented response removed')
            for status in sorted(responses_b.keys() - responses_a.keys()):
                emit('review', 'response.added', f'{loc}/{status}', 'New response status; check consumer handling')
            for status in sorted(responses_a.keys() & responses_b.keys()):
                r, s = old.resolve(responses_a[status]), new.resolve(responses_b[status])
                content(r, s, f'{loc}/{status}', 'response')
                if r.get('headers', {}) != s.get('headers', {}):
                    emit('review', 'response.headers', f'{loc}/{status}', 'Response headers changed')
            for field in ('security', 'servers', 'callbacks'):
                if ao.get(field, before.get(field)) != bo.get(field, after.get(field)):
                    emit('review', f'operation.{field}', loc, f'{field} changed')
    if before.get('components', {}).get('securitySchemes') != after.get('components', {}).get('securitySchemes'):
        emit('review', 'security.schemes', 'components/securitySchemes', 'Security scheme definitions changed')
    return sorted(set(findings))


def render_html(findings: list[Finding]) -> str:
    counts = {s: sum(f.severity == s for f in findings) for s in ('breaking', 'review', 'info')}
    esc = html.escape
    rows = ''.join(f'<tr><td><span class="{f.severity}">{f.severity}</span></td><td><code>{esc(f.code)}</code><br><strong>{esc(f.location)}</strong></td><td>{esc(f.message)}</td></tr>' for f in findings)
    cards = ''.join(f'<article><b>{n}</b><span>{s}</span></article>' for s, n in counts.items())
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ContractLens · Compatibility report</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0b1120;color:#e2e8f0;font:16px/1.6 system-ui}main{max-width:1100px;margin:auto;padding:64px 24px}small{color:#5eead4;letter-spacing:.2em}h1{font-size:clamp(32px,6vw,60px);letter-spacing:-.05em;margin:12px 0}p{color:#94a3b8}.cards{display:flex;gap:16px;margin:32px 0}article{flex:1;border:1px solid #334155;border-radius:16px;padding:24px;background:#111b2e}article b{display:block;font-size:40px}article span{text-transform:uppercase;font-size:12px;letter-spacing:.15em}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:20px 12px;border-bottom:1px solid #243148;overflow-wrap:anywhere}code{color:#94a3b8;font-size:12px}.breaking{color:#fda4af}.review{color:#fcd34d}.info{color:#5eead4}footer{margin-top:40px;color:#94a3b8;font-size:13px}@media(max-width:600px){.cards{gap:8px}article{padding:12px}td,th{padding:12px 6px;font-size:13px}}</style><main><small>CONTRACTLENS / COMPATIBILITY INTELLIGENCE</small><h1>Ship changes with clarity.</h1><p>Structural API compatibility report · OpenAPI 3 JSON</p><section class="cards">''' + cards + '</section><table><thead><tr><th>Impact</th><th>Rule / Location</th><th>Finding</th></tr></thead><tbody>' + (rows or '<tr><td colspan="3">No findings within the supported checks.</td></tr>') + '</tbody></table><footer>Review findings need human assessment. This report does not prove full API compatibility. Generated locally, without network requests.</footer></main></html>'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--format', choices=('text', 'json', 'html'), default='text')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--fail-on', choices=('breaking', 'review', 'never'), default='breaking')
    args = parser.parse_args(argv)
    try:
        data = [json.loads(p.read_text(encoding='utf-8')) for p in (args.before, args.after)]
        findings = compare(*data)
        if args.format == 'json':
            result = json.dumps({'version': __version__, 'findings': [asdict(f) for f in findings]}, indent=2)
        elif args.format == 'html':
            result = render_html(findings)
        else:
            result = '\n'.join(f'{f.severity.upper():8} {f.code} | {f.location} | {f.message}' for f in findings) or 'No findings within the supported checks.'
        if args.output:
            args.output.write_text(result + '\n', encoding='utf-8')
        else:
            print(result)
        return int(any(f.severity == 'breaking' or (args.fail_on == 'review' and f.severity == 'review') for f in findings) and args.fail_on != 'never')
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        print(f'contractlens: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
