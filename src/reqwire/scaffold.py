"""Scaffold supporting files and directories."""
from __future__ import absolute_import

import datetime
import io
import pathlib

import fasteners.process_lock
import ordered_set
import six

import reqwire.config
import reqwire.errors
import reqwire.helpers.requirements


MYPY = False
if MYPY:
    from typing import (  # noqa: F401
        Iterable,
        Iterator,
        Optional,
        Set,
        Type,
    )


__all__ = (
    'build_filename',
    'build_source_header',
    'DEFAULT_HEADER',
    'extend_source_file',
    'init_source_dir',
    'init_source_file',
)


MODELINES_HEADER = six.text_type("""\
# -*- mode: requirementstxt -*-
# vim: set ft=requirements
""")


#: The default header format string for requirement source files.
#:
#: The first two lines provide modeline comments for Sublime Text and
#: Vim.
#:
#: To enable requirements.txt completion and syntax highlighting in
#: Sublime Text, install the following plugins with Package Control:
#:
#: * `requirementstxt <https://github.com/wuub/requirementstxt>`_
#: * `STEmacsModelines <https://github.com/kvs/STEmacsModelines>`_
#:
#: For Vim, install the
#: `requirements syntax <https://github.com/raimon49/requirements.txt.vim>`_.
DEFAULT_HEADER = MODELINES_HEADER + six.text_type("""\
# Generated by reqwire on %c
{nested_cfiles}\
{nested_rfiles}\
{index_url}\
{extra_index_urls}
""")


def build_filename(working_directory,  # type: str
                   tag_name,           # type: str
                   extension='.in',    # type: str
                   prefix='src',       # type: str
                   ):
    # type: (...) -> pathlib.Path
    """Constructs a path to a tagged requirement source file.

    Args:
        working_directory: The parent directory of the source file.
        tag_name: The tag name.
        extension: The file extension. Defaults to *.in*.
        prefix: The subdirectory under the working directory to create
            the source file in. Defaults to *src*.

    """
    wd = pathlib.Path(working_directory) / prefix
    return wd / ''.join((tag_name, extension))


def build_source_header(format_string=None,     # type: Optional[str]
                        index_url=None,         # type: Optional[str]
                        extra_index_urls=None,  # type: Optional[Iterable[str]]
                        nested_cfiles=None,     # type: Optional[Set[str]]
                        nested_rfiles=None,     # type: Optional[Set[str]]
                        timestamp=None,     # type: Optional[datetime.datetime]
                        ):
    # type: (...) -> str
    """Builds a header for requirement source file.

    Args:
        format_string: A format string containing one or more of the
            following keys: **nested_cfiles**, **nested_rfiles**,
            **index_url**, and **extra_index_urls**. The format string
            may also include ``strftime`` formatting directives.
            Defaults to :const:`DEFAULT_HEADER`.
        index_url: A Python package index URL.
        extra_index_urls: Extra Python package index URLs.
        nested_cfiles: A set of nested constraint files.
        nested_rfiles: A set of nested requirement files.
        timestamp: A :class:`datetime.datetime` object. If not provided,
            defaults to the current datetime.

    Returns:
        The rendered header string.

    """
    if format_string is None:
        format_string = DEFAULT_HEADER

    if timestamp is None:
        timestamp = datetime.datetime.now()

    components = {
        'nested_cfiles': '',
        'nested_rfiles': '',
        'index_url': '',
        'extra_index_urls': '',
    }

    if nested_cfiles is not None:
        components['nested_cfiles'] = '\n'.join(
            '-c {}'.format(rfile)
            for rfile in nested_cfiles)
    if nested_rfiles is not None:
        components['nested_rfiles'] = '\n'.join(
            '-r {}'.format(rfile)
            for rfile in nested_rfiles)
    if index_url is not None:
        components['index_url'] = ' '.join(
            ('--index-url', index_url.strip()))
    if extra_index_urls is not None:
        components['extra_index_urls'] = '\n'.join(
            ' '.join(('--extra-index-url', extra_index_url))
            for extra_index_url in extra_index_urls)

    for key in components:
        if components[key]:
            components[key] += '\n'

    return timestamp.strftime(format_string).format(
        **components).strip() + '\n'


@fasteners.process_lock.interprocess_locked(str(reqwire.config.lockfile))
def extend_source_file(working_directory,             # type: str
                       tag_name,                      # type: str
                       specifiers,                    # type: Iterable[str]
                       extension='.in',               # type: str
                       index_url=None,                # type: Optional[str]
                       extra_index_urls=None,   # type: Optional[Set[str]]
                       lookup_index_urls=None,  # type: Optional[Set[str]]
                       prereleases=False,             # type: bool
                       resolve_canonical_names=True,  # type: bool
                       resolve_versions=True,         # type: bool
                       ):
    # type: (...) -> None
    """Adds requirements to an existing requirement source file.

    Args:
        working_directory: The parent directory of the source file.
        tag_name: The tag name.
        specifiers: A list of specifiers.
        extension: The file extension. Defaults to *.in*.
        index_url: A Python package index URL.
        extra_index_urls: Extra Python package index URLs.
        lookup_index_urls: Python package index URLs used to search
            for packages during resolving. This parameter is only useful
            if an attempt is made to add packages found only in indexes
            that are only specified in nested requirement source files.
        prereleases: Whether or not to include prereleases.
        resolve_canonical_names: Queries package indexes provided by
            **index_urls** for the canonical name of each
            specifier. For example, *flask* will get resolved to
            *Flask*.
        resolve_versions: Queries package indexes for latest package
            versions.

    """
    if extra_index_urls is None:
        extra_index_urls = ordered_set.OrderedSet()
    else:
        extra_index_urls = ordered_set.OrderedSet(extra_index_urls)

    filename = build_filename(
        working_directory=working_directory,
        tag_name=tag_name,
        extension=extension)
    req_file = reqwire.helpers.requirements.RequirementFile(str(filename))
    if filename.exists():
        if index_url is not None and index_url != req_file.index_url:
            raise reqwire.errors.IndexUrlMismatchError(
                '"{}" != "{}"'.format(index_url, req_file.index_url))
        elif index_url is None:
            index_url = req_file.index_url
            extra_index_urls |= req_file.extra_index_urls

    if lookup_index_urls is None:
        lookup_index_urls = {index_url} if index_url is not None else set()
        if extra_index_urls is not None:
            lookup_index_urls |= set(extra_index_urls)

        if not lookup_index_urls and req_file.index_urls:
            lookup_index_urls |= req_file.index_urls

    req_file.requirements |= reqwire.helpers.requirements.build_ireq_set(
        specifiers=specifiers,
        index_urls=lookup_index_urls,
        prereleases=prereleases,
        resolve_canonical_names=resolve_canonical_names,
        resolve_source_dir=str(pathlib.Path(working_directory).parent),
        resolve_versions=resolve_versions)

    resolved_requirements = reqwire.helpers.requirements.resolve_ireqs(
        requirements=req_file.requirements,
        prereleases=prereleases,
        intersect=True)

    nested_cfiles = ordered_set.OrderedSet(
        str(cf.filename.relative_to(filename.parent))
        for cf in req_file.nested_cfiles)
    nested_rfiles = ordered_set.OrderedSet(
        str(rf.filename.relative_to(filename.parent))
        for rf in req_file.nested_rfiles)

    reqwire.helpers.requirements.write_requirements(
        filename=str(filename),
        requirements=resolved_requirements,
        header=build_source_header(
            index_url=index_url,
            extra_index_urls=extra_index_urls,
            nested_cfiles=nested_cfiles,
            nested_rfiles=nested_rfiles))


def init_source_dir(working_directory,    # type: str
                    mode=0o777,           # type: int
                    create_parents=True,  # type: bool
                    exist_ok=False,       # type: bool
                    name='src',           # type: str
                    ):
    # type: (...) -> pathlib.Path
    """Creates a requirements source directory.

    Args:
        working_directory: The parent directory of the source file.
        mode: Permissions with which to create source file. Defaults to
            `0o777`.
        create_parents: Whether or not parent directories should be
            created if missing.
        exist_ok: Does not raise an :class:`OSError` if directory
            creation failed.
        name: The name of the subdirectory to create under the working
            directory. Defaults to *src*.

    """
    wd = pathlib.Path(working_directory)
    src = wd / name
    try:
        src.mkdir(mode=mode, parents=create_parents)
    except OSError:
        if not exist_ok:
            raise
    return src


def init_source_file(working_directory,      # type: str
                     tag_name,               # type: str
                     extension='.in',        # type: str
                     index_url=None,         # type: Optional[str]
                     extra_index_urls=None,  # type: Optional[Iterable[str]]
                     encoding=None,          # type: Optional[str]
                     errors=None,            # type: Optional[str]
                     mode=0o666,             # type: int
                     overwrite=False,        # type: bool
                     ):
    # type: (...) -> pathlib.Path
    """Creates a requirements source file.

    Args:
        working_directory: The requirements working directory.
        tag_name: The tag name.
        extension: The file extension. Defaults to ".in".
        index_url: Base URL of Python package index.
        extra_index_urls: Iterable of URLs of secondary package indexes.
        encoding: Passed to :func:`io.open` when creating source file.
        errors: Passed to :func:`io.open` when creating source file.
        mode: Permissions with which to create source file. Defaults to
            `0o666`.
        overwrite: Whether or not to overwrite an existing source file.

    Returns:
        Path to source file.

    """
    filename = build_filename(
        working_directory=working_directory,
        tag_name=tag_name,
        extension=extension)
    try:
        filename.touch(mode=mode)
    except OSError:
        if not overwrite:
            raise

    with io.open(str(filename), 'wb', encoding=encoding, errors=errors) as f:
        f.write(build_source_header().encode('utf-8'))

    return filename
