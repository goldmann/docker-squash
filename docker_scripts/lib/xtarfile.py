"""
This is a monkey patching for Python 2 that is required to handle PAX headers
in TAR files that are not decodable to UTF8. It leaves it undecoded and when
adding back to the tar archive the header is not encoded preserving the
original headers.

Reported in RH Bugzilla: https://bugzilla.redhat.com/show_bug.cgi?id=1194473

Original source code was taken from Python 2.7.9.

Credit goes to Vincent Batts:

  https://github.com/docker/docker-registry/pull/381
"""

import re
import tarfile


def _proc_pax(self, filetar):
    """Process an extended or global header as described in POSIX.1-2001."""
    # Read the header information.
    buf = filetar.fileobj.read(self._block(self.size))

    # A pax header stores supplemental information for either
    # the following file (extended) or all following files
    # (global).
    if self.type == tarfile.XGLTYPE:
        pax_headers = filetar.pax_headers
    else:
        pax_headers = filetar.pax_headers.copy()

    # Parse pax header information. A record looks like that:
    # "%d %s=%s\n" % (length, keyword, value). length is the size
    # of the complete record including the length field itself and
    # the newline. keyword and value are both UTF-8 encoded strings.
    regex = re.compile(r"(\d+) ([^=]+)=", re.U)
    pos = 0
    while True:
        match = regex.match(buf, pos)
        if not match:
            break

        length, keyword = match.groups()
        length = int(length)
        value = buf[match.end(2) + 1:match.start(1) + length - 1]

        try:
            keyword = keyword.decode("utf8")
        except Exception:
            pass

        try:
            value = value.decode("utf8")
        except Exception:
            pass

        pax_headers[keyword] = value
        pos += length

    # Fetch the next header.
    try:
        next = self.fromtarfile(filetar)
    except tarfile.HeaderError:
        raise tarfile.SubsequentHeaderError("missing or bad subsequent header")

    if self.type in (tarfile.XHDTYPE, tarfile.SOLARIS_XHDTYPE):
        # Patch the TarInfo object with the extended header info.
        next._apply_pax_info(pax_headers, filetar.encoding, filetar.errors)
        next.offset = self.offset

        if "size" in pax_headers:
            # If the extended header replaces the size field,
            # we need to recalculate the offset where the next
            # header starts.
            offset = next.offset_data
            if next.isreg() or next.type not in tarfile.SUPPORTED_TYPES:
                offset += next._block(next.size)
            filetar.offset = offset

    return next


def _create_pax_generic_header(cls, pax_headers, type=tarfile.XHDTYPE):
    """Return a POSIX.1-2001 extended or global header sequence
       that contains a list of keyword, value pairs. The values
       must be unicode objects.
    """
    records = []
    for keyword, value in pax_headers.iteritems():

        try:
            keyword = keyword.encode("utf8")
        except Exception:
            pass

        try:
            value = value.encode("utf8")
        except Exception:
            pass

        l = len(keyword) + len(value) + 3   # ' ' + '=' + '\n'
        n = p = 0
        while True:
            n = l + len(str(p))
            if n == p:
                break
            p = n
        records.append("%d %s=%s\n" % (p, keyword, value))
    records = "".join(records)

    # We use a hardcoded "././@PaxHeader" name like star does
    # instead of the one that POSIX recommends.
    info = {}
    info["name"] = "././@PaxHeader"
    info["type"] = type
    info["size"] = len(records)
    info["magic"] = tarfile.POSIX_MAGIC

    # Create pax header + record blocks.
    return cls._create_header(info, tarfile.USTAR_FORMAT) + \
        cls._create_payload(records)

tarfile.TarInfo._proc_pax = _proc_pax
tarfile.TarInfo._create_pax_generic_header = _create_pax_generic_header
