# Copyright (c) 2020  Red Hat, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Written by Jan Kaluza <jkaluza@redhat.com>

from odcs.server import db
from odcs.server.models import Compose
from odcs.common.types import COMPOSE_RESULTS
from odcs.server.pungi import PungiSourceType
from odcs.server.metrics import ComposesCollector
from .utils import ModelsBaseTest


class TestComposesCollector(ModelsBaseTest):

    def setUp(self):
        super(TestComposesCollector, self).setUp()
        self.collector = ComposesCollector()

    def test_composes_total(self):
        Compose.create(
            db.session, "unknown", PungiSourceType.MODULE, "testmodule:master",
            COMPOSE_RESULTS["repository"], 60)
        Compose.create(
            db.session, "me", PungiSourceType.KOJI_TAG, "f26",
            COMPOSE_RESULTS["repository"], 60)
        db.session.commit()

        r = self.collector.composes_total()
        for sample in r.samples:
            if (
                sample.labels["source_type"] in ["module", "tag"] and
                sample.labels["state"] == "wait"
            ):
                self.assertEqual(sample.value, 1)
            else:
                self.assertEqual(sample.value, 0)

    def test_raw_config_composes_count(self):
        for i in range(15):
            Compose.create(
                db.session, "unknown", PungiSourceType.RAW_CONFIG, "foo#bar",
                COMPOSE_RESULTS["repository"], 60)
        for i in range(10):
            Compose.create(
                db.session, "me", PungiSourceType.RAW_CONFIG, "foo#hash%d" % i,
                COMPOSE_RESULTS["repository"], 60)
        db.session.commit()
        r = self.collector.raw_config_composes_count()
        for sample in r.samples:
            if sample.labels["source"] == "foo#bar":
                self.assertEqual(sample.value, 15)
            elif sample.labels["source"] == "foo#other_commits_or_branches":
                self.assertEqual(sample.value, 10)
