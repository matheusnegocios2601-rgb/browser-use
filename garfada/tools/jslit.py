"""Parse JS object-literal data (no code execution) into Python objects."""
import json
import re
import sys

NUM = re.compile(r'-?\d+(\.\d+)?([eE][-+]?\d+)?')
IDENT = re.compile(r'[A-Za-z_$][\w$]*')


class P:
    def __init__(s, t, i):
        s.t, s.i = t, i

    def ws(s):
        while True:
            while s.t[s.i] in ' \t\r\n':
                s.i += 1
            if s.t.startswith('//', s.i):
                s.i = s.t.index('\n', s.i)
                continue
            return

    def val(s):
        s.ws()
        c = s.t[s.i]
        if c == '{':
            return s.obj()
        if c == '[':
            return s.arr()
        if c in '"\'':
            return s.string()
        m = NUM.match(s.t, s.i)
        if m:
            s.i = m.end()
            g = m.group()
            return float(g) if any(x in g for x in '.eE') else int(g)
        for lit, v in (('true', True), ('false', False), ('null', None)):
            if s.t.startswith(lit, s.i):
                s.i += len(lit)
                return v
        raise ValueError('bad token at %d: %r' % (s.i, s.t[s.i:s.i + 40]))

    def string(s):
        q = s.t[s.i]
        s.i += 1
        out = []
        while True:
            c = s.t[s.i]
            if c == '\\':
                n = s.t[s.i + 1]
                if n == 'x':
                    out.append(chr(int(s.t[s.i + 2:s.i + 4], 16)))
                    s.i += 4
                elif n == 'u':
                    out.append(chr(int(s.t[s.i + 2:s.i + 6], 16)))
                    s.i += 6
                else:
                    out.append({'n': '\n', 't': '\t'}.get(n, n))
                    s.i += 2
            elif c == q:
                s.i += 1
                return ''.join(out)
            else:
                out.append(c)
                s.i += 1

    def key(s):
        s.ws()
        if s.t[s.i] in '"\'':
            return s.string()
        m = IDENT.match(s.t, s.i)
        s.i = m.end()
        return m.group()

    def obj(s):
        s.i += 1
        o = {}
        while True:
            s.ws()
            if s.t[s.i] == '}':
                s.i += 1
                return o
            k = s.key()
            s.ws()
            assert s.t[s.i] == ':', s.t[s.i:s.i + 40]
            s.i += 1
            o[k] = s.val()
            s.ws()
            if s.t[s.i] == ',':
                s.i += 1

    def arr(s):
        s.i += 1
        a = []
        while True:
            s.ws()
            if s.t[s.i] == ']':
                s.i += 1
                return a
            a.append(s.val())
            s.ws()
            if s.t[s.i] == ',':
                s.i += 1


src = open(sys.argv[1], encoding='utf8').read()
out = {}
for name in ('foods_default', 'household_default', 'profiles_default'):
    marker = 'var %s = ' % name
    out[name] = P(src, src.index(marker) + len(marker)).val()
json.dump(out, open(sys.argv[2], 'w'), ensure_ascii=False)
print(len(out['foods_default']['foods']), len(out['household_default']['foods']))
print(json.dumps(out['profiles_default'], ensure_ascii=False)[:900])
