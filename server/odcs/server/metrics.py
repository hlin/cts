# -*- coding: utf-8 -*-

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

from sqlalchemy import func
from prometheus_client import CollectorRegistry
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily

from odcs.common.types import COMPOSE_STATES, PUNGI_SOURCE_TYPE_NAMES
from odcs.server.models import Compose


registry = CollectorRegistry()


class ComposesCollector(object):

    def composes_total(self):
        """
        Returns `composes_total` GaugeMetricFamily with number of composes
        for each state and source_type.
        """
        counter = GaugeMetricFamily(
            "composes_total", "Total number of composes", labels=["source_type", "state"]
        )
        for state in COMPOSE_STATES:
            for source_type in PUNGI_SOURCE_TYPE_NAMES:
                count = Compose.query.filter(
                    Compose.source_type == PUNGI_SOURCE_TYPE_NAMES[source_type],
                    Compose.state == COMPOSE_STATES[state],
                ).count()

                counter.add_metric([source_type, state], count)
        return counter

    def raw_config_composes_count(self):
        """
        Returns `raw_config_composes_count` CounterMetricFamily with number of raw_config
        composes for each `Compose.source`. For raw_config composes, the Compose.source is
        stored in the `raw_config_key#commit_or_branch` format. If particular `Compose.source` is
        generated only few times (less than 5), it is grouped by the `raw_config_key` and
        particular `commit_or_branch` is replaced with "other_commits_or_branches" string.

        This is needed to handle the situation when particular raw_config compose is generated
        just once using particular commit hash (and not a branch name). These single composes
        are not that important in the metrics and therefore we group them like that.
        """
        counter = CounterMetricFamily(
            "raw_config_composes_count",
            "Total number of raw_config composes per source", labels=["source"]
        )
        composes = Compose.query.with_entities(Compose.source, func.count(Compose.source)).filter(
            Compose.source_type == PUNGI_SOURCE_TYPE_NAMES["raw_config"]
        ).group_by(Compose.source).all()

        sources = {}
        for source, count in composes:
            if count < 5:
                name = "%s#other_commits_or_branches" % source.split("#")[0]
                if name not in sources:
                    sources[name] = 0
                sources[name] += count
            else:
                sources[source] = count

        for source, count in sources.items():
            counter.add_metric([source], count)

        return counter

    def collect(self):
        yield self.composes_total()
        yield self.raw_config_composes_count()


registry.register(ComposesCollector())
