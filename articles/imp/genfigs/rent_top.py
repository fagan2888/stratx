import support
import numpy as np

np.random.seed(1)

support.gen_topk_figs(n_trials=1, dataset="rent",
                      targetname='price',
                      min_samples_leaf=20,
                      cat_min_samples_leaf=2,  # unused; only numerical
                      title="NYC rent prices",
                      yrange=(200, 900),
                      yunits="$")
