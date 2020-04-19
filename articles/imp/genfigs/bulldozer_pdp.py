from sklearn.utils import resample
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import normalize
from sklearn.ensemble import RandomForestRegressor
from timeit import default_timer as timer
from sklearn.utils import resample

import shap
from sympy.simplify.radsimp import fraction_expand

#from support import load_bulldozer
import support
from stratx.partdep import plot_stratpd, plot_catstratpd
from stratx.featimp import importances

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

np.set_printoptions(precision=2, suppress=True, linewidth=300, threshold=2000)

np.random.seed(1)

n = 20_000
X, y = support.load_bulldozer(n)

I = importances(X, y,
                n_trials=5,
                # normalize=False,

                bootstrap=True,
                # bootstrap=False,
                # subsample_size=.7,

                min_samples_leaf=15,
                cat_min_samples_leaf=5,
                catcolnames={'AC', 'ModelID', 'auctioneerID'}
                )
print(I)

# pdpx, pdpy, ignored = \
#     plot_stratpd(X, y, colname='ProductSize', targetname='SalePrice',
#
#                  # n_trials=1,
#                  # n_trees=30,
#                  # bootstrap=True,
#                  # min_slopes_per_x=5*30,
#
#                  n_trials=10,
#                  min_slopes_per_x=5,
#                  min_samples_leaf=10,
#
#                  show_slope_lines=False,
#                  show_impact=True,
#                  figsize=(3.8,3.2),
#                  show_impact_line=False,
#                  show_impact_dots=False,
#                  impact_fill_color='#FEF5DC',
#                  # xrange=(1960,2010),
#                  # yrange=(-1000,45000)
#                  )
# plt.title(f"10 trials, min slopes 5\nmin_samples_leaf 10, ignored {ignored}", fontsize=10)
# # plt.title(f"1 trial, 30 trees, min slopes 5*ntrees, ignored {ignored}", fontsize=10)
# plt.tight_layout()
# plt.savefig(f"/Users/parrt/Desktop/james-YearMade.pdf", pad_inches=0)
# plt.show()

#


# y_ = y_.sample(frac=1.0, replace=False)
# X_['ModelID'] = X_['ModelID'].sample(frac=1.0, replace=False)

# uniq_catcodes, combined_avg_per_cat, ignored, merge_ignored = \
#     plot_catstratpd(X, y, colname='ModelID', targetname='SalePrice',
#                     # min_samples_leaf=2,
#                     n_trials=10,
#                     show_xticks=False,
#                     show_impact=True,
#                     min_y_shifted_to_zero=False,
#                     figsize=(20,5),
#                     yrange=(-150_000, 150_000),
#                     verbose=False)
# plt.title(f"n={n}, ignored = {ignored}, merge_ignored = {merge_ignored}")
# print("ignored",ignored, f"merge_ignored = {merge_ignored}")
# plt.tight_layout()
# plt.savefig(f"/Users/parrt/Desktop/james-ModelID-50k.pdf", pad_inches=0)
# # plt.savefig(f"/Users/parrt/Desktop/james-ModelID-10k-shuffled-x-not-y.pdf", pad_inches=0)
# # plt.savefig(f"/Users/parrt/Desktop/james-ModelID-10k-shuffled.pdf", pad_inches=0)
# plt.show()




# I = importances(X_, y_,
#                 min_samples_leaf=5,
#                 # min_slopes_per_x=5,
#                 n_trials=10,
#                 sort='Rank',
#                 catcolnames={'AC', 'ModelID'})
# print(I)
# I.to_csv("/tmp/t2.csv")

#plot_catstratpd(X_, y_, colname='ProductSize', targetname='SalePrice')


# plot_stratpd(X_, y_, colname='YearMade', targetname='SalePrice',
#              show_slope_lines=False,
#              show_impact=True,
#              min_samples_leaf=5,
#              min_slopes_per_x=7,
#              pdp_marker_cmap='coolwarm',#'YlGnBu',#'tab20b',
#              figsize=(4,3)
#              )
# plt.tight_layout()
# plt.savefig(f"/Users/parrt/Desktop/james-YearMade.pdf", pad_inches=0)
# plt.show()




# col = 'YearMade'
# plot_stratpd_gridsearch(X_, y_, colname=col, targetname='SalePrice',
#                         min_samples_leaf_values=(2,3,4,5,6,7),
#                         min_slopes_per_x_values=(2,3,5,6,7,8),
#                         show_slope_lines=False,
#                         show_impact=True
#                         #,yrange=(-20000,2000)
#                         )
# plt.tight_layout()
# plt.savefig(f"/Users/parrt/Desktop/james-{col}-grid.pdf", pad_inches=0)
# plt.show()

#
# plot_stratpd(X_, y_, colname='saledayofyear', targetname='SalePrice',
#              show_impact=True,
#              show_slope_lines=False)
# plt.tight_layout()
# plt.show()
# #
# plot_stratpd(X_, y_, colname='ProductSize', targetname='SalePrice',
#              show_impact=True,
#              show_slope_lines=False)
# plt.tight_layout()
# plt.show()




# I = importances(X_, y_, catcolnames={'AC', 'ModelID', 'ProductSize'},
#                 min_samples_leaf=10,
#                 min_slopes_per_x=5)
# print(I)


col = 'age'
# col = 'ProductSize'

# y_ = y_.sample(frac=1.0, replace=False)
# plot_catstratpd_gridsearch(X_, y_, 'ModelID', 'SalePrice',
#                            min_samples_leaf_values=(5, 8, 10, 15, 20),
#                            sort=None,
#                            cellwidth=4.5,
#                            n_trials=3,
#                            show_xticks=False,
#                            show_all_cat_deltas=False,
#                            min_y_shifted_to_zero=False)
# plt.savefig(f"/Users/parrt/Desktop/james-ModelID-grid-shuffled.pdf", pad_inches=0)
# # plt.savefig(f"/Users/parrt/Desktop/james-ModelID-grid.pdf", pad_inches=0)
# plt.show()

# plot_catstratpd(X_, y_, 'YearMade', 'SalePrice',
#                 min_samples_leaf=10,
#                 show_mean_line=True,
#                 sort=None,
#                 show_xticks=False,
#                 min_y_shifted_to_zero=False)

