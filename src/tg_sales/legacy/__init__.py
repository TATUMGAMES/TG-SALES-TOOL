"""Databases from the earlier desktop version (SQLite), read only to transfer them.

The SQLite file is never modified: it is copied, the copy is upgraded to the
last desktop schema, and the copy is read by :mod:`tg_sales.legacy.transfer`.
"""
