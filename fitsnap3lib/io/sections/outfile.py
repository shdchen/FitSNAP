from os import path
from fitsnap3lib.io.sections.sections import Section
from fitsnap3lib.parallel_tools import ParallelTools
from os import path


#pt = ParallelTools()


class Outfile(Section):

    def __init__(self, name, config, args):
        super().__init__(name, config, args)
        self.pt = ParallelTools()
        self.allowedkeys = ['output_style',
                            'metrics',
                            'metrics_style',
                            'potential',
                            'detailed_errors']
        self._check_section()

        self._outfile()
        self.output_style = self.get_value("OUTFILE", "output_style", "SNAP")
        self.metrics_style = self.get_value("OUTFILE", "metrics_style", "MD")
        self.delete()

    def _outfile(self):
        self.metric_file = self.check_path(self.get_value("OUTFILE", "metrics", "fitsnap_metrics"))
        self.potential_name = self.check_path(self.get_value("OUTFILE", "potential", "fitsnap_potential"))
        return
