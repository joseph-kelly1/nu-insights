"""Moving source files must not change which data the app reads."""

import os
from pathlib import Path
import tempfile
import unittest

from backend import advisor, catalog_editions, db_loader, exam_credit, paths


class RepositoryPathsTest(unittest.TestCase):
    def test_default_data_and_database_paths_do_not_depend_on_working_directory(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                self.assertEqual(Path(advisor.DB_FILE), paths.DB_FILE)
                self.assertEqual(Path(db_loader.DB_FILE), paths.DB_FILE)
                self.assertEqual(Path(db_loader.DEPARTMENTS_FILE), paths.DATA_DIR / 'departments.json')
                self.assertEqual(Path(db_loader.COURSES_DIR), paths.DATA_DIR / 'courses')
                self.assertEqual(exam_credit.DATA_DIR, paths.DATA_DIR / 'exams')
                self.assertEqual(catalog_editions.data_root(advisor.DB_FILE), paths.DATA_DIR)
                self.assertTrue(Path(db_loader.DEPARTMENTS_FILE).is_file())
            finally:
                os.chdir(previous)

    def test_custom_database_keeps_snapshots_isolated_from_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'courses.db'
            self.assertEqual(catalog_editions.data_root(database), database.resolve().parent / 'data')
            self.assertEqual(catalog_editions.editions(database), [])
