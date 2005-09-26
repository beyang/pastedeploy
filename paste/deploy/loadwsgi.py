import os
import re
import urllib
from ConfigParser import ConfigParser
import pkg_resources

__all__ = ['loadapp', 'loadserver', 'loadfilter']

############################################################
## Utility functions
############################################################

def import_string(s):
    return pkg_resources.EntryPoint.parse("x="+s).load(False)

def _aslist(obj):
    """
    Turn object into a list; lists and tuples are left as-is, None
    becomes [], and everything else turns into a one-element list.
    """
    if obj is None:
        return []
    elif isinstance(obj, (list, tuple)):
        return obj
    else:
        return [obj]

def _flatten(lst):
    """
    Flatten a nested list.
    """
    if not isinstance(lst, (list, tuple)):
        return [lst]
    result = []
    for item in lst:
        result.extend(_flatten(item))
    return result

class NicerConfigParser(ConfigParser):

    def __init__(self, filename, *args, **kw):
        ConfigParser.__init__(self, *args, **kw)
        self.filename = filename

    def _interpolate(self, section, option, rawval, vars):
        try:
            return ConfigParser._interpolate(
                self, section, option, rawval, vars)
        except Exception, e:
            args = list(e.args)
            args[0] = 'Error in file %s, [%s] %s=%r: %s' % (
                self.filename, section, option, rawval)
            e.args = tuple(args)
            raise

############################################################
## Object types
############################################################

class _ObjectType(object):

    def __init__(self, name, egg_protocols, config_prefixes):
        self.name = name
        self.egg_protocols = map(_aslist, _aslist(egg_protocols))
        self.config_prefixes = map(_aslist, _aslist(config_prefixes))

    def __repr__(self):
        return '<%s protocols=%r prefixes=%r>' % (
            self.name, self.egg_protocols, self.config_prefixees)

    def invoke(self, context):
        assert context.protocol in _flatten(self.egg_protocols)
        return context.object(context.global_conf, **context.local_conf)

APP = _ObjectType(
    'application',
    ['paste.app_factory', 'paste.composit_factory'],    
    [['app', 'application'], 'composit', 'pipeline', 'filter-app'])

def APP_invoke(context):
    if context.protocol == 'paste.composit_factory':
        return context.object(context.loader, context.global_conf,
                              **context.local_conf)
    elif context.protocol == 'paste.app_factory':
        return context.object(context.global_conf, **context.local_conf)
    else:
        assert 0, "Protocol %r unknown" % context.protocol

APP.invoke = APP_invoke

FILTER = _ObjectType(
    'filter',
    [['paste.filter_factory', 'paste.filter_app_factory']],
    ['filter'])

def FILTER_invoke(context):
    if context.protocol == 'paste.filter_factory':
        return context.object(context.global_conf, **context.local_conf)
    elif context.protocol == 'paste.filter_app_factory':
        def filter_wrapper(wsgi_app):
            # This should be an object, so it has a nicer __repr__
            return context.object(wsgi_app, context.global_conf,
                                  **context.local_conf)
        return filter_wrapper
    else:
        assert 0, "Protocol %r unknown" % context.protocol

FILTER.invoke = FILTER_invoke

SERVER = _ObjectType(
    'server',
    [['paste.server_factory', 'paste.server_runner']],
    ['server'])

def SERVER_invoke(context):
    if context.protocol == 'paste.server_factory':
        return context.object(context.global_conf, **context.local_conf)
    elif context.protocol == 'paste.server_runner':
        def server_wrapper(wsgi_app):
            # This should be an object, so it has a nicer __repr__
            return context.object(wsgi_app, context.global_conf,
                                  **context.local_conf)
        return server_wrapper
    else:
        assert 0, "Protocol %r unknown" % context.protocol

SERVER.invoke = SERVER_invoke

# Virtual type: (@@: There's clearly something crufty here;
# this probably could be more elegant)
PIPELINE = _ObjectType(
    'pipeline',
    [], [])

def PIPELINE_invoke(context):
    app = context.app_context.create()
    filters = [c.create() for c in context.filter_contexts]
    filters.reverse()
    for filter in filters:
        app = filter(app)
    return app

PIPELINE.invoke = PIPELINE_invoke

# Virtual type:
FILTER_APP = _ObjectType(
    'filter_app',
    [], [])

def FILTER_APP_invoke(context):
    next_app = context.next_context.create()
    filter = context.filter_context.create()
    return filter(next_app)

FILTER_APP.invoke = FILTER_APP_invoke

FILTER_WITH = _ObjectType(
    'filtered_app', [], [])

def FILTER_WITH_invoke(context):
    filter = context.filter_context.create()
    app = APP_invoke(context)
    return filter(app)

FILTER_WITH.invoke = FILTER_WITH_invoke

############################################################
## Loaders
############################################################

def loadapp(uri, name=None, **kw):
    return loadobj(APP, uri, name=name, **kw)

def loadfilter(uri, name=None, **kw):
    return loadobj(FILTER, uri, name=name, **kw)

def loadserver(uri, name=None, **kw):
    return loadobj(SERVER, uri, name=name, **kw)

_loaders = {}

def loadobj(object_type, uri, name=None, relative_to=None,
            global_conf=None):
    context = loadcontext(
        object_type, uri, name=name, relative_to=relative_to,
        global_conf=global_conf)
    return context.create()

def loadcontext(object_type, uri, name=None, relative_to=None,
                global_conf=None):
    if '#' in uri:
        if name is None:
            uri, name = uri.split('#', 1)
        else:
            # @@: Ignore fragment or error?
            uri = uri.split('#', 1)[0]
    scheme, path = uri.split(':', 1)
    scheme = scheme.lower()
    if scheme not in _loaders:
        raise LookupError(
            "URI scheme not known: %r (from %s)"
            % (scheme, ', '.join(_loaders.keys())))
    return _loaders[scheme](
        object_type,
        uri, path, name=name, relative_to=relative_to,
        global_conf=global_conf)

def _loadconfig(object_type, uri, path, name, relative_to,
                global_conf):
    # De-Windowsify the paths:
    path = path.replace('\\', '/')
    if not path.startswith('/'):
        if not relative_to:
            raise ValueError(
                "Cannot resolve relative uri %r; no context keyword "
                "argument given" % uri)
        relative_to = relative_to.replace('\\', '/')
        if relative_to.endswith('/'):
            path = relative_to + path
        else:
            path = relative_to + '/' + path
    if path.startswith('///'):
        path = path[2:]
    path = urllib.unquote(path)
    loader = ConfigLoader(path)
    return loader.get_context(object_type, name, global_conf)

_loaders['config'] = _loadconfig

def _loadegg(object_type, uri, spec, name, relative_to,
             global_conf):
    loader = EggLoader(spec)
    return loader.get_context(object_type, name, global_conf)

_loaders['egg'] = _loadegg

############################################################
## Loaders
############################################################

class _Loader(object):

    def get_app(self, name=None, global_conf=None):
        return self.app_context(
            name=name, global_conf=global_conf).create()

    def get_filter(self, name=None, global_conf=None):
        return self.filter_context(
            name=name, global_conf=global_conf).create()

    def get_server(self, name=None, global_conf=None):
        return self.server_context(
            name=name, global_conf=global_conf).create()

    def app_context(self, name=None, global_conf=None):
        return self.get_context(
            APP, name=name, global_conf=global_conf)

    def filter_context(self, name=None, global_conf=None):
        return self.get_context(
            FILTER, name=name, global_conf=global_conf)

    def server_context(self, name=None, global_conf=None):
        return self.get_context(
            SERVER, name=name, global_conf=global_conf)

    _absolute_re = re.compile(r'^[a-zA-Z]+:')
    def absolute_name(self, name):
        """
        Returns true if the name includes a scheme
        """
        if name is None:
            return False
        return self._absolute_re.search(name)        

class ConfigLoader(_Loader):

    def __init__(self, filename):
        self.filename = filename
        self.parser = ConfigParser(self.filename)
        # Don't lower-case keys:
        self.parser.optionxform = str
        # Stupid ConfigParser ignores files that aren't found, so
        # we have to add an extra check:
        if not os.path.exists(filename):
            raise OSError(
                "File %s not found" % filename)
        self.parser.read(filename)
        self.parser._defaults.setdefault(
            'here', os.path.dirname(os.path.abspath(filename)))

    def get_context(self, object_type, name=None, global_conf=None):
        if self.absolute_name(name):
            return loadcontext(object_type, name,
                               relative_to=os.path.dirname(self.filename),
                               global_conf=global_conf)
        section = self.find_config_section(
            object_type, name=name)
        if global_conf is None:
            global_conf = {}
        else:
            global_conf = global_conf.copy()
        defaults = self.parser.defaults()
        global_conf.update(defaults)
        local_conf = {}
        global_additions = {}
        get_from_globals = {}
        for option in self.parser.options(section):
            if option.startswith('set '):
                name = option[4:].strip()
                global_additions[name] = global_conf[name] = (
                    self.parser.get(section, option))
            elif option.startswith('get '):
                name = option[4:].strip()
                get_from_globals[name] = self.parser.get(section, option)
            else:
                if option in defaults:
                    # @@: It's a global option (?), so skip it
                    continue
                local_conf[option] = self.parser.get(section, option)
        for local_var, glob_var in get_from_globals.items():
            local_conf[local_var] = global_conf[glob_var]
        if object_type is APP and 'filter-with' in local_conf:
            filter_with = local_conf.pop('filter-with')
        else:
            filter_with = None
        if 'require' in local_conf:
            for spec in local_conf['require'].split():
                pkg_resources.require(spec)
            del local_conf['require']
        if section.startswith('filter-app:'):
            context = self._filter_app_context(
                object_type, section, name=name,
                global_conf=global_conf, local_conf=local_conf,
                global_additions=global_additions)
        elif section.startswith('pipeline:'):
            context = self._pipeline_app_context(
                object_type, section, name=name,
                global_conf=global_conf, local_conf=local_conf,
                global_additions=global_additions)
        elif 'use' in local_conf:
            context = self._context_from_use(
                object_type, local_conf, global_conf, global_additions,
                section)
        else:
            context = self._context_from_explicit(
                object_type, local_conf, global_conf, global_additions,
                section)
        if filter_with is not None:
            filter_context = self.filter_context(
                name=filter_with, global_conf=global_conf)
            context.object_type = FILTER_WITH
            context.filter_context = filter_context
        return context

    def _context_from_use(self, object_type, local_conf, global_conf,
                          global_additions, section):
        use = local_conf.pop('use')
        context = self.get_context(
            object_type, name=use, global_conf=global_conf)
        context.global_conf.update(global_additions)
        context.local_conf.update(local_conf)
        # @@: Should loader be overwritten?
        context.loader = self
        return context

    def _context_from_explicit(self, object_type, local_conf, global_conf,
                               global_addition, section):
        possible = []
        for protocol_options in object_type.egg_protocols:
            for protocol in protocol_options:
                if protocol in local_conf:
                    possible.append((protocol, local_conf[protocol]))
                    break
        if len(possible) > 1:
            raise LookupError(
                "Multiple protocols given in section %r: %s"
                % (section, possible))
        if not possible:
            raise LookupError(
                "No loader given in section %r" % section)
        found_protocol, found_expr = possible[0]
        del local_conf[found_protocol]
        value = import_string(found_expr)
        context = LoaderContext(
            value, object_type, found_protocol,
            global_conf, local_conf, self)
        return context

    def _filter_app_context(self, object_type, section, name,
                            global_conf, local_conf, global_additions):
        if 'next' not in local_conf:
            raise LookupError(
                "The [%s] section in %s is missing a 'next' setting"
                % (section, self.filename))
        next_name = local_conf.pop('next')
        context = LoaderContext(None, FILTER_APP, None, global_conf,
                                local_conf, self)
        context.next_context = self.get_context(
            APP, next_name, global_conf)
        if 'use' in local_conf:
            context.filter_context = self._context_from_use(
                FILTER, local_conf, global_conf, global_additions,
                section)
        else:
            context.filter_context = self._context_from_explicit(
                FILTER, local_conf, global_conf, global_additions,
                section)
        return context

    def _pipeline_app_context(self, object_type, section, name,
                              global_conf, local_conf, global_additions):
        if 'pipeline' not in local_conf:
            raise LookupError(
                "The [%s] section in %s is missing a 'pipeline' setting"
                % (section, self.filename))
        pipeline = local_conf.pop('pipeline').split()
        if local_conf:
            raise LookupError(
                "The [%s] pipeline section in %s has extra "
                "(disallowed) settings: %s"
                % (', '.join(local_conf.keys())))
        context = LoaderContext(None, PIPELINE, None, global_conf,
                                local_conf, self)
        context.app_context = self.get_context(
            APP, pipeline[-1], global_conf)
        context.filter_contexts = [
            self.get_context(FILTER, name, global_conf)
            for name in pipeline[:-1]]
        return context

    def find_config_section(self, object_type, name=None):
        """
        Return the section name with the given name prefix (following the
        same pattern as ``protocol_desc`` in ``config``.  It must have the
        given name, or for ``'main'`` an empty name is allowed.  The
        prefix must be followed by a ``:``.

        Case is *not* ignored.
        """
        possible = []
        for name_options in object_type.config_prefixes:
            for name_prefix in name_options:
                found = self._find_sections(
                    self.parser.sections(), name_prefix, name)
                if found:
                    possible.extend(found)
                    break
        if not possible:
            raise LookupError(
                "No section %r (prefixed by %s) found in config %s"
                % (name,
                   ' or '.join(map(repr, _flatten(object_type.config_prefixes))),
                   self.filename))
        if len(possible) > 1:
            raise LookupError(
                "Ambiguous section names %r for section %r (prefixed by %s) "
                "found in config %s"
                % (possible, name,
                   ' or '.join(map(repr, _flatten(object_type.config_prefixes))),
                   self.filename))
        return possible[0]

    def _find_sections(self, sections, name_prefix, name):
        found = []
        if name is None:
            if name_prefix in sections:
                found.append(name_prefix)
            name = 'main'
        for section in sections:
            if section.startswith(name_prefix+':'):
                if section[len(name_prefix)+1:].strip() == name:
                    found.append(section)
        return found


class EggLoader(_Loader):

    def __init__(self, spec):
        self.spec = spec

    def get_context(self, object_type, name=None, global_conf=None):
        if self.absolute_name(name):
            return loadcontext(object_type, name,
                               global_conf=global_conf)
        entry_point, protocol = self.find_egg_entry_point(
            object_type, name=name)
        return LoaderContext(
            entry_point,
            object_type,
            protocol,
            global_conf or {}, {},
            self)

    def find_egg_entry_point(self, object_type, name=None):
        """
        Returns the (entry_point, protocol) for the with the given
        ``name``.
        """
        if name is None:
            name = 'main'
        possible = []
        for protocol_options in object_type.egg_protocols:
            for protocol in protocol_options:
                entry = pkg_resources.get_entry_info(
                    self.spec,
                    protocol,
                    name)
                if entry is not None:
                    possible.append((entry.load(), protocol))
                    break
        if not possible:
            # Better exception
            dist = pkg_resources.get_distribution(self.spec)
            raise LookupError(
                "Entry point %r not found in egg %r (dir: %s; protocols: %s; "
                "entry_points: %s)"
                % (name, self.spec,
                   dist.location,
                   ', '.join(_flatten(object_type.egg_protocols)),
                   ', '.join(_flatten([
                (pkg_resources.get_entry_info(self.spec, prot, name) or {}).keys()
                for prot in protocol_options] or '(no entry points)'))))
        if len(possible) > 1:
            raise LookupError(
                "Ambiguous entry points for %r in egg %r (protocols: %s)"
                % (name, self.spec, ', '.join(_flatten(protocol_options))))
        return possible[0]

class LoaderContext(object):

    def __init__(self, obj, object_type, protocol,
                 global_conf, local_conf, loader):
        self.object = obj
        self.object_type = object_type
        self.protocol = protocol
        self.global_conf = global_conf
        self.local_conf = local_conf
        self.loader = loader

    def create(self):
        return self.object_type.invoke(self)
