THEOLOGIA SEARCH
=================

Theologia Search is a desktop search application for a curated collection of
Christian theological books. This package is self-contained: Python, PySide6,
Qt, the search index, fonts, and artwork are included. No separate package
installation is required.

STARTING THE APP
----------------
Use the Start Menu or Desktop shortcut to open Theologia Search. The installed
folder contains TheologiaSearch.exe if you need to launch it directly.

REGULAR SEARCH
--------------
Enter a word or phrase in the main search box and select Search. Results are
shown independently under Before Nicene, Nicene to Reformation, and
Post-Reformation. Select a result to inspect its evidence and surrounding
context.

ADVANCED SEARCH
---------------
Use Advanced Search to combine a concept with metadata filters:

  Author            The work or evidence author.
  Mentioned author  A person discussed in the evidence, not the work author.
  Period            Historical period of the work author.
  Book              Source volume or book title.
  Chapter           Chapter or section heading.

The Author filter is used for historical grouping and period classification.
For example, a City of God passage discussing Origen is attributed to
Augustine as the work author, while Origen remains available through the
Mentioned author filter.

DATA INCLUDED
-------------
This release contains the searchable SQLite dataset and application resources.
It does not include the raw knowledge-base files or original source PDFs.

The installed folder also contains CATALOG.txt, a complete list of indexed
authors and book volumes with evidence and period statistics.

LICENSES
--------
The installed folder contains a license subfolder with the Theologia Search
non-commercial license, third-party notices, the SIL Open Font License texts
for the bundled Cinzel and EB Garamond fonts, and CCEL copyright-policy
information.

The generated SQLite database includes indexed content derived in part from
CCEL editions. CCEL materials remain subject to the rights and restrictions
applicable to each individual work. The bundled fonts remain under the SIL
Open Font License 1.1, which permits some commercial uses of the font files
that are not permitted for Theologia Search itself.

The packaged index contains approximately:

  Authors:   66 author-period records
  Volumes:   287 indexed source volumes
  Evidence:  118,242 evidence records

SEARCH HISTORY
--------------
Search history is stored in the current Windows user's local application data
folder and does not modify the bundled database.

TROUBLESHOOTING
---------------
If the application reports that the installation is incomplete or damaged,
run the installer again or uninstall and reinstall Theologia Search. Do not
delete the bundled semantic_index.sqlite file.

The application is designed for Windows 10 and Windows 11.
