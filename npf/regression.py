from typing import Tuple

from npf.grapher import *
from npf.repository import *
from npf.testie import Testie, SectionScript, ScriptInitException
from npf.types.dataset import Dataset


class Regression:
    def __init__(self, repo: Repository):
        self.repo = repo

    def accept_diff(self, testie, result, old_result):
        result = np.asarray(result)
        old_result = np.asarray(old_result)
        n = testie.reject_outliers(result).mean()
        old_n = testie.reject_outliers(old_result).mean()
        diff = abs(old_n - n) / old_n
        accept = testie.config["acceptable"]
        accept += abs(result.std() * testie.config["accept_variance"] / n)
        return diff <= accept, diff

    def compare(self, testie:Testie, variable_list, all_results: Dataset, build, old_all_results, last_build,
                allow_supplementary=True,init_done=False) -> Tuple[int,int]:
        """
        Compare two sets of results for the given list of variables and returns the amount of failing test
        :param init_done: True if initialization for current testie is already done (init sections for the testie and its import)
        :param testie: One testie to get the config from
        :param variable_list:
        :param all_results:
        :param build:
        :param old_all_results:
        :param last_build:
        :param allow_supplementary:
        :return: the amount of failed tests (0 means all passed)
        """

        if not old_all_results:
            return 0, 0

        tests_passed = 0
        tests_total = 0
        supp_done = False
        tot_runs = testie.config["n_runs"] + testie.config["n_supplementary_runs"]
        for v in variable_list:
            tests_total += 1
            run = Run(v)
            results_types = all_results.get(run)
            # TODO : some config could implement acceptable range no matter the old value
            if results_types is None or len(results_types) == 0:
                continue

            need_supp = False
            for result_type, result in results_types.items():
                if run in old_all_results and not old_all_results[run] is None:
                    old_result = old_all_results[run].get(result_type, None)
                    if old_result is None:
                        continue

                    ok, diff = self.accept_diff(testie, result, old_result)
                    if not ok and len(result) < tot_runs and allow_supplementary:
                        need_supp = True
                        break
                elif last_build:
                    if not testie.options.quiet_regression:
                        print("No old values for %s for version %s." % (run, last_build.version))
                    if old_all_results:
                        old_all_results[run] = {}

            if need_supp:
                if not testie.options.quiet_regression:
                    print(
                        "Difference of %.2f%% is outside acceptable margin for %s. Running supplementary tests..." % (
                            diff * 100, run.format_variables()))

                if not init_done:
                    testie.do_init_all(build=build, options=testie.options, do_test=testie.options.do_test)
                    init_done = True
                if hasattr(testie, 'late_variables'):
                    v = testie.late_variables.execute(v, testie)
                new_results_types, output, err = testie.execute(build, run, v,
                                                                n_runs=testie.config["n_supplementary_runs"],
                                                                allowed_types={SectionScript.TYPE_SCRIPT})

                for result_type, results in new_results_types.items():
                    results_types[result_type] += results

                if not testie.options.quiet_regression:
                    print("Result after supplementary tests done :", results_types)

                if new_results_types is not None:
                    supp_done = True
                    all_results[run] = results_types
                    for result_type, result in results_types.items():
                        old_result = old_all_results[run].get(result_type, None)
                        if old_result is None:
                            continue
                        ok, diff = self.accept_diff(testie, result, old_result)
                        if ok is False:
                            break
                else:
                    ok = True

            if len(results_types) > 0:
                if not ok:
                    print(
                        "ERROR: Test %s is outside acceptable margin between %s and %s : difference of %.2f%% !" % (
                            testie.filename, build.version, last_build.version, diff * 100))
                else:
                    tests_passed += 1
                    if not testie.options.quiet_regression:
                        print("Acceptable difference of %.2f%% for %s" % ((diff * 100), run.format_variables()))

        if supp_done:
            build.writeversion(testie, all_results)
        return tests_passed, tests_total

    def regress_all_testies(self, testies: List['Testie'], options, history: int = 1) -> Tuple[Build, List[Dataset]]:
        """
        Execute all testies passed in argument for the last build of the regressor associated repository
        :param history: Start regression at last build + 1 - history
        :param testies: List of testies
        :param options: Options object
        :return: the lastbuild and one Dataset per testies or None if could not build
        """
        repo = self.repo
        datasets = []

        build = repo.get_last_build(history=history)

        nok = 0

        for testie in testies:
            print("[%s] Running testie %s on version %s..." % (repo.name, testie.filename, build.version))
            regression = self
            if repo.last_build:
                try:
                    old_all_results = repo.last_build.load_results(testie)
                except FileNotFoundError:
                    old_all_results = None
            else:
                old_all_results = None
            try:
                all_results,init_done = testie.execute_all(build, prev_results=build.load_results(testie), options=options,
                                                 do_test=options.do_test)
                if all_results is None:
                    return None, None
            except ScriptInitException:
                return None, None

            variables_passed, variables_total = regression.compare(testie, testie.variables, all_results, build,
                                                                   old_all_results,
                                                                   repo.last_build,
                                                                   init_done=init_done)
            if variables_passed == variables_total:
                nok += 1
            datasets.append(all_results)
            testie.n_variables_passed = variables_passed
            testie.n_variables = variables_total

        build.writeResults()
        repo.last_build = build

        build.n_passed = nok
        build.n_tests = len(testies)

        return build, datasets
