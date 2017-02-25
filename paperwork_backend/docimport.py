#    Paperwork - Using OCR to grep dead trees the easy way
#    Copyright (C) 2012-2014  Jerome Flesch
#
#    Paperwork is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    Paperwork is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with Paperwork.  If not, see <http://www.gnu.org/licenses/>.

"""
Document import (PDF, images, etc)
"""

import gettext
import logging

from gi.repository import GLib
from gi.repository import Gio
from PIL import Image

from .pdf.doc import PdfDoc
from .img.doc import ImgDoc

_ = gettext.gettext
logger = logging.getLogger(__name__)


class ImportResult(object):
    BASE_STATS = {
        _("PDF"): 0,
        _("Document(s)"): 0,
        _("Image file(s)"): 0,
        _("Page(s)"): 0,
    }

    def __init__(self, select_doc=None, select_page=None,
                 new_docs=[], upd_docs=[],
                 new_docs_pages=[], upd_docs_pages=[],
                 stats={}):
        if select_doc is None and select_page is not None:
            select_doc = select_page.doc

        if select_doc is not None and select_page is None:
            if select_doc.nb_pages > 0:
                select_page = select_doc.pages[0]

        self.select_doc = select_doc
        self.select_page = select_page
        self.new_docs = new_docs
        self.upd_docs = upd_docs
        self.new_docs_pages = new_docs_pages
        self.upd_docs_pages = upd_docs_pages
        self.stats = self.BASE_STATS.copy()
        self.stats.update(stats)

    @property
    def has_import(self):
        return len(self.new_docs) > 0 or len(self.upd_docs) > 0


class PdfImporter(object):
    """
    Import a single PDF file as a document
    """

    def __init__(self):
        pass

    @staticmethod
    def can_import(file_uris, current_doc=None):
        """
        Check that the specified file looks like a PDF
        """
        if len(file_uris) <= 0:
            return False
        for uri in file_uris:
            if not uri.lower().endswith(".pdf"):
                return False
        return True

    @staticmethod
    def import_doc(file_uris, docsearch, current_doc=None):
        """
        Import the specified PDF file
        """
        doc = None
        docs = []
        pages = []

        for file_uri in file_uris:
            f = Gio.File.parse_name(file_uri)
            if docsearch.is_hash_in_index(PdfDoc.hash_file(f.get_path())):
                logger.info("Document %s already found in the index. Skipped"
                            % (f.get_path()))
                return ImportResult()

            doc = PdfDoc(docsearch.rootdir)
            logger.info("Importing doc '%s' ..." % file_uri)
            error = doc.import_pdf(file_uri)
            if error:
                raise Exception("Import of {} failed: {}".format(
                    file_uri, error
                ))
            docs.append(doc)
            pages += [p for p in doc.pages]

        return ImportResult(
            select_doc=doc, new_docs=docs,
            new_docs_pages=pages,
            stats={
                _("PDF"): len(file_uris),
                _("Document(s)"): len(file_uris),
                _("Page(s)"): len(pages),
            }
        )

    def get_mimetypes(self):
        return [
            ("PDF", "application/pdf"),
        ]

    def __str__(self):
        return _("Import PDF")


class PdfDirectoryImporter(object):
    """
    Import many PDF files as many documents
    """

    def __init__(self):
        pass

    @staticmethod
    def __get_all_children(parent):
        """
        Find all the children files from parent
        """
        children = parent.enumerate_children(
            Gio.FILE_ATTRIBUTE_STANDARD_NAME,
            Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
            None)
        for child in children:
            name = child.get_name()
            child = parent.get_child(name)
            try:
                for child in PdfDirectoryImporter.__get_all_children(child):
                    yield child
            except GLib.GError:
                yield child

    @staticmethod
    def can_import(file_uris, current_doc=None):
        """
        Check that the specified file looks like a directory containing many
        pdf files
        """
        if len(file_uris) <= 0:
            return False
        try:
            for file_uri in file_uris:
                parent = Gio.File.parse_name(file_uri)
                for child in PdfDirectoryImporter.__get_all_children(parent):
                    if child.get_basename().lower().endswith(".pdf"):
                        return True
        except GLib.GError:
            pass
        return False

    @staticmethod
    def import_doc(file_uris, docsearch, current_doc=None):
        """
        Import the specified PDF files
        """

        doc = None
        docs = []
        pages = []

        for file_uri in file_uris:
            logger.info("Importing PDF from '%s'" % (file_uri))
            parent = Gio.File.parse_name(file_uri)
            idx = 0

            for child in PdfDirectoryImporter.__get_all_children(parent):
                if not child.get_basename().lower().endswith(".pdf"):
                    continue
                if docsearch.is_hash_in_index(
                            PdfDoc.hash_file(child.get_path())
                        ):
                    logger.info(
                        "Document %s already found in the index. Skipped",
                        (child.get_path())
                    )
                    continue
                doc = PdfDoc(docsearch.rootdir)
                error = doc.import_pdf(child.get_uri())
                if error:
                    continue
                docs.append(doc)
                pages.append([p for p in doc.pages])
                idx += 1
        return ImportResult(
            select_doc=doc, new_docs=docs,
            new_docs_pages=pages,
            stats={
                _("PDF"): len(docs),
                _("Document(s)"): len(docs),
                _("Page(s)"): sum([d.nb_pages for d in docs]),
            },
        )

    def get_mimetypes(self):
        return [
            (_("PDF folder"), "inode/directory"),
        ]

    def __str__(self):
        return _("Import each PDF in the folder as a new document")


class ImageImporter(object):
    """
    Import a single image file (in a format supported by PIL). It is either
    added to a document (if one is specified) or as a new document (--> with a
    single page)
    """

    def __init__(self):
        pass

    @staticmethod
    def can_import(file_uris, current_doc=None):
        """
        Check that the specified file looks like an image supported by PIL
        """
        if len(file_uris) <= 0:
            return False
        for file_uri in file_uris:
            valid = False
            for ext in ImgDoc.IMPORT_IMG_EXTENSIONS:
                if file_uri.lower().endswith(ext):
                    valid = True
                    break
            if not valid:
                return False
        return True

    @staticmethod
    def import_doc(file_uris, docsearch, current_doc=None):
        """
        Import the specified images
        """
        if current_doc is None or current_doc.is_new:
            if not current_doc:
                current_doc = ImgDoc(docsearch.rootdir)
            new_docs = [current_doc]
            upd_docs = []
        else:
            new_docs = []
            upd_docs = [current_doc]
        new_docs_pages = []
        upd_docs_pages = []
        page = None

        for file_uri in file_uris:
            logger.info("Importing doc '%s'" % (file_uri))

            file = Gio.File.new_for_uri(file_uri)
            img = Image.open(file.get_path())
            page = current_doc.add_page(img, [])

            if new_docs == []:
                upd_docs_pages.append(page)
            else:
                new_docs_pages.append(page)

        return ImportResult(
            select_doc=current_doc, select_page=page,
            new_docs=new_docs, upd_docs=upd_docs,
            new_docs_pages=new_docs_pages,
            upd_docs_pages=upd_docs_pages,
            stats={
                _("Image file(s)"): len(file_uris),
                _("Document(s)"): 0 if new_docs == [] else 1,
                _("Page(s)"): len(new_docs_pages) + len(upd_docs_pages),
            }
        )

    def get_mimetypes(self):
        return [
            ("BMP", "image/x-ms-bmp"),
            ("GIF", "image/gif"),
            ("JPEG", "image/jpeg"),
            ("PNG", "image/png"),
            ("TIFF", "image/tiff"),
        ]

    def __str__(self):
        return _("Append the image to the current document")


IMPORTERS = [
    PdfDirectoryImporter(),
    PdfImporter(),
    ImageImporter(),
]


def get_possible_importers(file_uris, current_doc=None):
    """
    Return all the importer objects that can handle the specified file.

    Possible imports may vary depending on the currently active document
    """
    importers = []
    for importer in IMPORTERS:
        if importer.can_import(file_uris, current_doc):
            importers.append(importer)
    return importers
