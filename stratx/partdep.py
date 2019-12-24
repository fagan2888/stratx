import numpy as np
from numpy import nan, where
import pandas as pd
from typing import Mapping, List, Tuple
import matplotlib.pyplot as plt
from  matplotlib.collections import LineCollection
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from scipy.stats import binned_statistic
import warnings
import collections
from timeit import default_timer as timer

from dtreeviz.trees import *
from snowballstemmer.dutch_stemmer import lab0
from numba import jit, prange
import numba


'''
def leaf_samples_general(rf, X:np.ndarray):
    """
    Return a list of arrays where each array is the set of X sample indexes
    residing in a single leaf of some tree in rf forest.
    """
    ntrees = len(rf.estimators_)
    leaf_ids = rf.apply(X) # which leaf does each X_i go to for each tree?
    d = pd.DataFrame(leaf_ids, columns=[f"tree{i}" for i in range(ntrees)])
    d = d.reset_index() # get 0..n-1 as column called index so we can do groupby
    """
    d looks like:
        index	tree0	tree1	tree2	tree3	tree4
    0	0	    8	    3	    4	    4	    3
    1	1	    8	    3	    4	    4	    3
    """
    leaf_samples = []
    for i in range(ntrees):
        """
        Each groupby gets a list of all X indexes associated with same leaf. 4 leaves would
        get 4 arrays of X indexes; e.g.,
        array([array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]),
               array([10, 11, 12, 13, 14, 15]), array([16, 17, 18, 19, 20]),
               array([21, 22, 23, 24, 25, 26, 27, 28, 29]), ... )
        """
        sample_idxs_in_leaf = d.groupby(f'tree{i}')['index'].apply(lambda x: x.values)
        leaf_samples.extend(sample_idxs_in_leaf) # add [...sample idxs...] for each leaf
    return leaf_samples
'''

def leaf_samples(rf, X_not_col:np.ndarray):
    """
    Return a list of arrays where each array is the set of X sample indexes
    residing in a single leaf of some tree in rf forest. For example, if there
    are 4 leaves (in one or multiple trees), we might return:

        array([array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]),
           array([10, 11, 12, 13, 14, 15]), array([16, 17, 18, 19, 20]),
           array([21, 22, 23, 24, 25, 26, 27, 28, 29]))
    """
    ntrees = len(rf.estimators_)
    leaf_samples = []
    leaf_ids = rf.apply(X_not_col)  # which leaf does each X_i go to for sole tree?
    for t in range(ntrees):
        # Group by id and return sample indexes
        uniq_ids = np.unique(leaf_ids[:,t])
        sample_idxs_in_leaves = [np.where(leaf_ids[:, t] == id) for id in uniq_ids]
        leaf_samples.extend(sample_idxs_in_leaves)
    return leaf_samples


def collect_point_betas(X, y, colname, leaves, nbins:int):
    ignored = 0
    leaf_xranges = []
    leaf_slopes = []
    point_betas = np.full(shape=(len(X),), fill_value=np.nan)

    for samples in leaves: # samples is set of obs indexes that live in a single leaf
        leaf_all_x = X.iloc[samples]
        leaf_x = leaf_all_x[colname].values
        leaf_y = y.iloc[samples].values
        # Right edge of last bin is max(leaf_x) but that means we ignore the last value
        # every time. Tweak domain right edge a bit so max(leaf_x) falls in last bin.
        last_bin_extension = 0.0000001
        domain = (np.min(leaf_x), np.max(leaf_x)+last_bin_extension)
        bins = np.linspace(*domain, num=nbins+1, endpoint=True)
        binned_idx = np.digitize(leaf_x, bins) # bin number for values in leaf_x
        for b in range(1, len(bins)+1):
            bin_x = leaf_x[binned_idx == b]
            bin_y = leaf_y[binned_idx == b]
            if len(bin_x) < 2: # could be none or 1 in bin
                ignored += len(bin_x)
                continue
            r = (np.min(bin_x), np.max(bin_x))
            if len(bin_x)<2 or np.isclose(r[0], r[1]):
    #             print(f'ignoring {bin_x} -> {bin_y} for same range')
                ignored += len(bin_x)
                continue
            lm = LinearRegression()
            leaf_obs_idx_for_bin = np.nonzero((leaf_x>=bins[b-1]) &(leaf_x<bins[b]))
            obs_idx = samples[leaf_obs_idx_for_bin]
            lm.fit(bin_x.reshape(-1, 1), bin_y)
            point_betas[obs_idx] = lm.coef_[0]
            leaf_slopes.append(lm.coef_[0])
            leaf_xranges.append(r)

    leaf_slopes = np.array(leaf_slopes)
    return leaf_xranges, leaf_slopes, point_betas, ignored


def partial_dependence(X:pd.DataFrame, y:pd.Series, colname:str,
                       min_slopes_per_x=15,
                       parallel_jit=True,
                       n_trees=1, min_samples_leaf=10, bootstrap=False, max_features=1.0,
                       supervised=True,
                       verbose=False):
    """
    Internal computation of partial dependence information about X[colname]'s effect on y.
    Also computes partial derivative of y with respect to X[colname].

    :param X: 
    :param y: 
    :param colname: 
    :param min_slopes_per_x:   ignore pdp y values derived from too few slopes (less than .3% of num records)
                            tried percentage of max slope count but was too variable; this is same count across all features
    :param n_trees:
    :param min_samples_leaf: 
    :param bootstrap: 
    :param max_features: 
    :param supervised: 
    :param verbose: 

    Returns:
        leaf_xranges    The ranges of X[colname] partitions


        leaf_slopes     Associated slope for each leaf xrange

        dx              The change in x from one non-NaN unique X[colname] to the next

        dydx            The slope at each non-NaN unique X[colname]

        pdpx            The non-NaN unique X[colname] values

        pdpy            The effect of each non-NaN unique X[colname] on y; effectively
                        the cumulative sum (integration from X[colname] x to z for all
                        z in X[colname]). The first value is always 0.

        ignored         How many samples from len(X) total records did we have to
                        ignore because of samples in leaves with identical X[colname]
                        values.
    """
    X_not_col = X.drop(colname, axis=1).values
    X_col = X[colname]
    if supervised:
        rf = RandomForestRegressor(n_estimators=n_trees,
                                   min_samples_leaf=min_samples_leaf,
                                   bootstrap=bootstrap,
                                   max_features=max_features)
        rf.fit(X_not_col, y)
        if verbose:
            print(f"Strat Partition RF: dropping {colname} training R^2 {rf.score(X_not_col, y):.2f}")

    else:
        """
        Wow. Breiman's trick works in most cases. Falls apart on Boston housing MEDV target vs AGE
        """
        if verbose: print("USING UNSUPERVISED MODE")
        X_synth, y_synth = conjure_twoclass(X)
        rf = RandomForestRegressor(n_estimators=n_trees,
                                   min_samples_leaf=min_samples_leaf,
                                   bootstrap=bootstrap,
                                   max_features=max_features,
                                   oob_score=False)
        rf.fit(X_synth.drop(colname, axis=1), y_synth)

    if verbose:
        leaves = leaf_samples(rf, X_not_col)
        nnodes = rf.estimators_[0].tree_.node_count
        print(f"Partitioning 'x not {colname}': {nnodes} nodes in (first) tree, "
              f"{len(rf.estimators_)} trees, {len(leaves)} total leaves")

    leaf_xranges, leaf_slopes, ignored = \
        collect_discrete_slopes(rf, X, y, colname)

    # print('leaf_xranges', leaf_xranges)
    # print('leaf_slopes', leaf_slopes)

    real_uniq_x = np.array(sorted(np.unique(X_col)))
    if verbose:
        print(f"discrete StratPD num samples ignored {ignored}/{len(X)} for {colname}")

    if parallel_jit:
        slope_at_x, slope_counts_at_x = \
            avg_values_at_x_jit(real_uniq_x, leaf_xranges, leaf_slopes)
    else:
        slope_at_x, slope_counts_at_x = \
            avg_values_at_x_nonparallel_jit(real_uniq_x, leaf_xranges, leaf_slopes)

    # Drop any nan slopes; implies we have no reliable data for that range
    # Last slope is nan since no data after last x value so that will get dropped too
    # Also cut out any pdp x for which we don't have enough support (num slopes avg'd together)
    # Make sure to drop slope_counts_at_x, uniq_x values too :)
    notnan_idx = ~np.isnan(slope_at_x)
    relevant_slopes = slope_counts_at_x >= min_slopes_per_x
    idx = notnan_idx & relevant_slopes
    slope_at_x = slope_at_x[idx]
    slope_counts_at_x = slope_counts_at_x[idx]
    pdpx = real_uniq_x[idx]

    dx = np.diff(pdpx)
    dydx = slope_at_x[:-1] # ignore last point as dx is always one smaller
    y_deltas = dydx * dx
    # print(f"y_deltas: {y_deltas}")
    pdpy = np.cumsum(y_deltas)                    # we lose one value here
    pdpy = np.concatenate([np.array([0]), pdpy])  # add back the 0 we lost

    return leaf_xranges, leaf_slopes, slope_counts_at_x, dx, slope_at_x, pdpx, pdpy, ignored


def plot_stratpd_binned(X, y, colname, targetname,
                 ntrees=1, min_samples_leaf=10, bootstrap=False,
                 max_features=1.0,
                 nbins=3,  # piecewise binning
                 nbins_smoothing=None,  # binning of overall X[colname] space in plot
                 supervised=True,
                 ax=None,
                 xrange=None,
                 yrange=None,
                 title=None,
                 nlines=None,
                 show_xlabel=True,
                 show_ylabel=True,
                 show_pdp_line=False,
                 show_slope_lines=True,
                 pdp_marker_size=5,
                 pdp_line_width=.5,
                 slope_line_color='#2c7fb8',
                 slope_line_width=.5,
                 slope_line_alpha=.3,
                 pdp_line_color='black',
                 pdp_marker_color='black',
                 verbose=False
                 ):
    if supervised:
        rf = RandomForestRegressor(n_estimators=ntrees,
                                   min_samples_leaf=min_samples_leaf,
                                   bootstrap=bootstrap,
                                   max_features=max_features)
        rf.fit(X.drop(colname, axis=1), y)
        if verbose:
            print(f"Strat Partition RF: dropping {colname} training R^2 {rf.score(X.drop(colname, axis=1), y):.2f}")

    else:
        """
        Wow. Breiman's trick works in most cases. Falls apart on Boston housing MEDV target vs AGE
        """
        if verbose: print("USING UNSUPERVISED MODE")
        X_synth, y_synth = conjure_twoclass(X)
        rf = RandomForestRegressor(n_estimators=ntrees,
                                   min_samples_leaf=min_samples_leaf,
                                   bootstrap=bootstrap,
                                   max_features=max_features,
                                   oob_score=False)
        rf.fit(X_synth.drop(colname, axis=1), y_synth)

    leaves = leaf_samples(rf, X.drop(colname, axis=1))
    nnodes = rf.estimators_[0].tree_.node_count
    if verbose:
        print(f"Partitioning 'x not {colname}': {nnodes} nodes in (first) tree, "
              f"{len(rf.estimators_)} trees, {len(leaves)} total leaves")

    leaf_xranges, leaf_slopes, point_betas, ignored = \
        collect_point_betas(X, y, colname, leaves, nbins)
    Xbetas = np.vstack([X[colname].values, point_betas]).T # get x_c, beta matrix
    # Xbetas = Xbetas[Xbetas[:,0].argsort()] # sort by x coordinate (not needed)

    #print(f"StratPD num samples ignored {ignored}/{len(X)} for {colname}")

    x = Xbetas[:, 0]
    domain = (np.min(x), np.max(x))  # ignores any max(x) points as no slope info after that
    if nbins_smoothing is None:
        # use all unique values as bin edges if no bin width
        bins_smoothing = np.array(sorted(np.unique(x)))
    else:
        bins_smoothing = np.linspace(*domain, num=nbins_smoothing + 1, endpoint=True)

    noinfo = np.isnan(Xbetas[:, 1])
    Xbetas = Xbetas[~noinfo]

    avg_slopes_per_bin, _, _ = binned_statistic(x=Xbetas[:, 0], values=Xbetas[:, 1],
                                                bins=bins_smoothing, statistic='mean')

    # beware: avg_slopes_per_bin might have nan for empty bins
    bin_deltas = np.diff(bins_smoothing)
    delta_ys = avg_slopes_per_bin * bin_deltas  # compute y delta across bin width to get up/down bump for this bin

    # print('bins_smoothing', bins_smoothing, ', deltas', bin_deltas)
    # print('avgslopes', delta_ys)

    # manual cumsum
    delta_ys = np.concatenate([np.array([0]), delta_ys])  # we start at 0 for min(x)
    pdpx = []
    pdpy = []
    cumslope = 0.0
    # delta_ys_ = np.concatenate([np.array([0]), delta_ys])  # we start at 0 for min(x)
    for x, slope in zip(bins_smoothing, delta_ys):
        if np.isnan(slope):
            # print(f"{x:5.3f},{cumslope:5.1f},{slope:5.1f} SKIP")
            continue
        cumslope += slope
        pdpx.append(x)
        pdpy.append(cumslope)
        # print(f"{x:5.3f},{cumslope:5.1f},{slope:5.1f}")
    pdpx = np.array(pdpx)
    pdpy = np.array(pdpy)

    # PLOT

    if ax is None:
        fig, ax = plt.subplots(1,1)

    # Draw bin left edge markers; ignore bins with no data (nan)
    ax.scatter(pdpx, pdpy,
               s=pdp_marker_size, c=pdp_marker_color)

    if show_pdp_line:
        ax.plot(pdpx, pdpy,
                lw=pdp_line_width, c=pdp_line_color)

    if xrange is not None:
        ax.set_xlim(*xrange)
    else:
        ax.set_xlim(*domain)
    if yrange is not None:
        ax.set_ylim(*yrange)

    if show_slope_lines:
        segments = []
        for xr, slope in zip(leaf_xranges, leaf_slopes):
            w = np.abs(xr[1] - xr[0])
            delta_y = slope * w
            closest_x_i = np.abs(pdpx - xr[0]).argmin() # find curve point for xr[0]
            closest_x = pdpx[closest_x_i]
            closest_y = pdpy[closest_x_i]
            one_line = [(closest_x, closest_y), (closest_x+w, closest_y + delta_y)]
            segments.append( one_line )

        # if nlines is not None:
        #     nlines = min(nlines, len(segments))
        #     idxs = np.random.randint(low=0, high=len(segments), size=nlines)
        #     segments = np.array(segments)[idxs]

        lines = LineCollection(segments, alpha=slope_line_alpha, color=slope_line_color, linewidths=slope_line_width)
        ax.add_collection(lines)

    if show_xlabel:
        ax.set_xlabel(colname)
    if show_ylabel:
        ax.set_ylabel(targetname)
    if title is not None:
        ax.set_title(title)

    return leaf_xranges, leaf_slopes, Xbetas, pdpx, pdpy, ignored


def plot_stratpd(X:pd.DataFrame, y:pd.Series, colname:str, targetname:str,
                 min_slopes_per_x=15,  # ignore pdp y values derived from too few slopes (drop 0.003 of n, 0.3th percentile)
                 ntrees=1, min_samples_leaf=10, bootstrap=False,
                 max_features=1.0,
                 supervised=True,
                 ax=None,
                 xrange=None,
                 yrange=None,
                 title=None,
                 show_xlabel=True,
                 show_ylabel=True,
                 show_pdp_line=False,
                 show_slope_lines=True,
                 show_slope_counts=True,
                 show_mean_line=True,
                 pdp_marker_size=5,
                 pdp_line_width=.5,
                 slope_line_color='#2c7fb8',
                 slope_line_width=.5,
                 slope_line_alpha=.3,
                 pdp_line_color='black',
                 pdp_marker_color='black',
                 title_fontsize=11,
                 label_fontsize=10,
                 ticklabel_fontsize=10,
                 barchart_size = 0.1,  # if show_slope_counts, what ratio of vertical space should barchart use at bottom?
                 barchar_alpha = 0.7,
                 verbose=False
                 ):
    """
    Plot the partial dependence of X[colname] on y.

    Returns:
        leaf_xranges    The ranges of X[colname] partitions


        leaf_slopes     Associated slope for each leaf xrange

        dx              The change in x from one non-NaN unique X[colname] to the next

        dydx            The slope at each non-NaN unique X[colname]

        pdpx            The non-NaN unique X[colname] values

        pdpy            The effect of each non-NaN unique X[colname] on y; effectively
                        the cumulative sum (integration from X[colname] x to z for all
                        z in X[colname]). The first value is always 0.

        ignored         How many samples from len(X) total records did we have to
                        ignore because of samples in leaves with identical X[colname]
                        values.
    """
    leaf_xranges, leaf_slopes, slope_counts_at_x, dx, dydx, pdpx, pdpy, ignored = \
        partial_dependence(X=X, y=y, colname=colname, min_slopes_per_x=min_slopes_per_x,
                           n_trees=ntrees, min_samples_leaf=min_samples_leaf,
                           bootstrap=bootstrap, max_features=max_features, supervised=supervised,
                           verbose=verbose)

    if ax is None:
        fig, ax = plt.subplots(1,1)

    ax.scatter(pdpx, pdpy, s=pdp_marker_size, c=pdp_marker_color, label=colname)

    if show_pdp_line:
        ax.plot(pdpx, pdpy, lw=pdp_line_width, c=pdp_line_color)

    domain = (np.min(X[colname]), np.max(X[colname]))  # ignores any max(x) points as no slope info after that

    min_y = min(pdpy)
    max_y = max(pdpy)
    if show_slope_lines:
        segments = []
        for xr, slope in zip(leaf_xranges, leaf_slopes):
            w = np.abs(xr[1] - xr[0])
            delta_y = slope * w
            closest_x_i = np.abs(pdpx - xr[0]).argmin() # find curve point for xr[0]
            closest_x = pdpx[closest_x_i]
            closest_y = pdpy[closest_x_i]
            slope_line_endpoint_y = closest_y + delta_y
            one_line = [(closest_x, closest_y), (closest_x + w, slope_line_endpoint_y)]
            segments.append( one_line )
            if slope_line_endpoint_y < min_y:
                min_y = slope_line_endpoint_y
            elif slope_line_endpoint_y > max_y:
                max_y = slope_line_endpoint_y

        lines = LineCollection(segments, alpha=slope_line_alpha, color=slope_line_color, linewidths=slope_line_width)
        ax.add_collection(lines)

    if xrange is not None:
        ax.set_xlim(*xrange)
    else:
        ax.set_xlim(*domain)
    if yrange is not None:
        ax.set_ylim(*yrange)
    else:
        ax.set_ylim(min_y, max_y)

    if show_slope_counts:
        ax2 = ax.twinx()
        # scale y axis so the max count height is 10% of overall chart
        ax2.set_ylim(0, max(slope_counts_at_x) * 1/barchart_size)
        # draw just 0 and max count
        ax2.yaxis.set_major_locator(plt.FixedLocator([0, max(slope_counts_at_x)]))
        ax2.bar(x=pdpx, height=slope_counts_at_x, width=(max(pdpx)-min(pdpx)+1)/len(pdpx),
                facecolor='#BABABA', align='edge', alpha=barchar_alpha)
        ax2.set_ylabel(f"{colname} slope count", labelpad=-12, fontsize=label_fontsize)
        # shift other y axis down 10% to make room
        if yrange is not None:
            ax.set_ylim(yrange[0]-(yrange[1]-yrange[0])*.1, yrange[1])
        else:
            ax.set_ylim(min_y-(max_y-min_y)*.1, max_y)
        ax2.tick_params(axis='both', which='major', labelsize=ticklabel_fontsize)

    if show_mean_line:
        m = np.mean(np.abs(pdpy))
        ax.plot(domain, [m,m], '--', lw=.5, c='black')
        # add a tick for the mean in y axis
        ax.set_yticks(list(ax.get_yticks()) + [m])

    if show_xlabel:
        ax.set_xlabel(colname, fontsize=label_fontsize)
    if show_ylabel:
        ax.set_ylabel(targetname, fontsize=label_fontsize)
    if title is not None:
        ax.set_title(title, fontsize=title_fontsize)

    ax.tick_params(axis='both', which='major', labelsize=ticklabel_fontsize)

    return leaf_xranges, leaf_slopes, slope_counts_at_x, pdpx, pdpy, ignored


@jit(nopython=True)
def discrete_xc_space(x: np.ndarray, y: np.ndarray):
    """
    Use the unique x values within a leaf to dynamically compute the bins,
    rather then using a fixed nbins hyper parameter. Group the leaf x,y by x
    and collect the average y.  The unique x and y averages are the new x and y pairs.
    The slope for each x is:

        (y_{i+1} - y_i) / (x_{i+1} - x_i)

    If the ordinal/ints are exactly one unit part, then it's just y_{i+1} - y_i. If
    they are not consecutive, we do not ignore isolated x_i as it ignores too much data.
    E.g., if x is [1,3,4] and y is [9,8,10] then the x=2 coordinate is spanned as part
    of 1 to 3. The two slopes are [(8-9)/(3-1), (10-8)/(4-3)] and bin widths are [2,1].

    If there is exactly one unique x value in the leaf, the leaf provides no information
    about how x_c contributes to changes in y. We have to ignore this leaf.
    """
    ignored = 0

    # Group by x, take mean of all y with same x value (they come back sorted too)
    uniq_x = np.unique(x)
    avg_y = np.array([y[x==ux].mean() for ux in uniq_x])

    if len(uniq_x)==1:
        # print(f"ignore {len(x)} in discrete_xc_space")
        ignored += len(x)
        return np.array([[0]],dtype=x.dtype), np.array([0.0]), ignored

    bin_deltas = np.diff(uniq_x)
    y_deltas = np.diff(avg_y)
    leaf_slopes = y_deltas / bin_deltas  # "rise over run"
    leaf_xranges = np.array(list(zip(uniq_x, uniq_x[1:])))

    return leaf_xranges, leaf_slopes, ignored

def collect_discrete_slopes(rf, X, y, colname):
    """
    For each leaf of each tree of the random forest rf (trained on all features
    except colname), get the leaf samples then isolate the column of interest X values
    and the target y values. Perform another partition of X[colname] vs y and do
    piecewise linear regression to get the slopes in various regions of X[colname].
    We don't need to subtract the minimum y value before regressing because
    the slope won't be different. (We are ignoring the intercept of the regression line).

    Return for each leaf, the ranges of X[colname] partitions, num obs per x range,
    associated slope for each range

    Only does discrete now after doing pointwise continuous slopes differently.
    """
    # start = timer()
    leaf_slopes = []  # drop or rise between discrete x values
    leaf_xranges = [] # drop is from one discrete value to next

    ignored = 0

    X_col = X[colname].values
    X_not_col = X.drop(colname, axis=1)
    leaves = leaf_samples(rf, X_not_col)
    y = y.values

    if False:
        nnodes = rf.estimators_[0].tree_.node_count
        print(f"Partitioning 'x not {colname}': {nnodes} nodes in (first) tree, "
              f"{len(rf.estimators_)} trees, {len(leaves)} total leaves")

    for samples in leaves:
        leaf_x = X_col[samples]
        # leaf_x = one_leaf_samples[]#.reshape(-1,1)
        leaf_y = y[samples]

        if np.abs(np.min(leaf_x) - np.max(leaf_x)) < 1.e-8: # faster than np.isclose()
            # print(f"ignoring xleft=xright @ {r[0]}")
            ignored += len(leaf_x)
            continue

        leaf_xranges_, leaf_slopes_, ignored_ = \
            discrete_xc_space(leaf_x, leaf_y)

        leaf_slopes.extend(leaf_slopes_)
        leaf_xranges.extend(leaf_xranges_)
        ignored += ignored_

    leaf_xranges = np.array(leaf_xranges)
    leaf_slopes = np.array(leaf_slopes)

    # stop = timer()
    # if verbose: print(f"collect_discrete_slopes {stop - start:.3f}s")
    return leaf_xranges, leaf_slopes, ignored


def avg_values_at_x_nojit(uniq_x, leaf_ranges, leaf_slopes):
    """
    Compute the weighted average of leaf_slopes at each uniq_x.

    Value at max(x) is NaN since we have no data beyond that point.
    """
    nx = len(uniq_x)
    nslopes = len(leaf_slopes)
    slopes = np.zeros(shape=(nx, nslopes))
    # collect the slope for each range (taken from a leaf) as collection of
    # flat lines across the same x range
    i = 0
    for xr, slope in zip(leaf_ranges, leaf_slopes):
        s = np.full(nx, slope, dtype=float)
        # now trim line so it's only valid in range xr;
        # don't set slope on right edge
        s[np.where( (uniq_x < xr[0]) | (uniq_x >= xr[1]) )] = np.nan
        slopes[:, i] = s
        i += 1

    # The value could be genuinely zero so we use nan not 0 for out-of-range
    # Now average horiz across the matrix, averaging within each range
    # Wrap nanmean() in catcher to avoid "Mean of empty slice" warning, which
    # comes from some rows being purely NaN; I should probably look at this sometime
    # to decide whether that's hiding a bug (can there ever be a nan for an x range)?
    # Oh right. We might have to ignore some leaves (those with single unique x values)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        avg_value_at_x = np.nanmean(slopes, axis=1)
        # how many slopes avg'd together to get avg
        slope_counts_at_x = nslopes - np.isnan(slopes).sum(axis=1)

    # return average slope at each unique x value and how many slopes included in avg at each x
    return avg_value_at_x, slope_counts_at_x


# We get about 20% boost from parallel but limits use of other parallelism it seems;
# i get crashes when using multiprocessing package on top of this.
# If using n_jobs=1 all the time for importances, then turn jit=False so this
# method is not used
@jit(nopython=True, parallel=True) # use prange not range.
def avg_values_at_x_jit(uniq_x, leaf_ranges, leaf_slopes):
    """
    Compute the weighted average of leaf_slopes at each uniq_x.

    Value at max(x) is NaN since we have no data beyond that point.
    """
    nx = len(uniq_x)
    nslopes = len(leaf_slopes)
    slopes = np.zeros(shape=(nx, nslopes))
    # collect the slope for each range (taken from a leaf) as collection of
    # flat lines across the same x range

    for i in prange(nslopes):
        xr, slope = leaf_ranges[i], leaf_slopes[i]

        # s = np.full(nx, slope)#, dtype=float)
        # s[np.where( (uniq_x < xr[0]) | (uniq_x >= xr[1]) )] = np.nan
        # slopes[:, i] = s

        # Compute slope all the way across uniq_x but then trim line so
        # slope is only valid in range xr; don't set slope on right edge
        slopes[:, i] = np.where( (uniq_x < xr[0]) | (uniq_x >= xr[1]), np.nan, slope)


    # The value could be genuinely zero so we use nan not 0 for out-of-range
    # Now average horiz across the matrix, averaging within each range
    # Wrap nanmean() in catcher to avoid "Mean of empty slice" warning, which
    # comes from some rows being purely NaN; I should probably look at this sometime
    # to decide whether that's hiding a bug (can there ever be a nan for an x range)?
    # Oh right. We might have to ignore some leaves (those with single unique x values)

    # Compute:
    #   avg_value_at_x = np.mean(slopes[good], axis=1)  (numba doesn't allow axis arg)
    #   slope_counts_at_x = nslopes - np.isnan(slopes).sum(axis=1)
    avg_value_at_x = np.zeros(shape=nx)
    slope_counts_at_x = np.zeros(shape=nx)
    for i in prange(nx):
        row = slopes[i, :]
        n_nan = np.sum(np.isnan(row))
        avg_value_at_x[i] = np.nan if n_nan==nslopes else np.nanmean(row)
        slope_counts_at_x[i] = nslopes - n_nan

    # return average slope at each unique x value and how many slopes included in avg at each x
    return avg_value_at_x, slope_counts_at_x


# Hideous copying to get different kinds of jit'ing. This is slower by 20%
# than other version but can run in parallel with multiprocessing package.
@jit(nopython=True)
def avg_values_at_x_nonparallel_jit(uniq_x, leaf_ranges, leaf_slopes):
    """
    Compute the weighted average of leaf_slopes at each uniq_x.

    Value at max(x) is NaN since we have no data beyond that point.
    """
    nx = len(uniq_x)
    nslopes = len(leaf_slopes)
    slopes = np.zeros(shape=(nx, nslopes))
    # collect the slope for each range (taken from a leaf) as collection of
    # flat lines across the same x range

    for i in range(nslopes):
        xr, slope = leaf_ranges[i], leaf_slopes[i]

        # s = np.full(nx, slope)#, dtype=float)
        # s[np.where( (uniq_x < xr[0]) | (uniq_x >= xr[1]) )] = np.nan
        # slopes[:, i] = s

        # Compute slope all the way across uniq_x but then trim line so
        # slope is only valid in range xr; don't set slope on right edge
        slopes[:, i] = np.where( (uniq_x < xr[0]) | (uniq_x >= xr[1]), np.nan, slope)


    # The value could be genuinely zero so we use nan not 0 for out-of-range
    # Now average horiz across the matrix, averaging within each range
    # Wrap nanmean() in catcher to avoid "Mean of empty slice" warning, which
    # comes from some rows being purely NaN; I should probably look at this sometime
    # to decide whether that's hiding a bug (can there ever be a nan for an x range)?
    # Oh right. We might have to ignore some leaves (those with single unique x values)

    # Compute:
    #   avg_value_at_x = np.mean(slopes[good], axis=1)  (numba doesn't allow axis arg)
    #   slope_counts_at_x = nslopes - np.isnan(slopes).sum(axis=1)
    avg_value_at_x = np.zeros(shape=nx)
    slope_counts_at_x = np.zeros(shape=nx)
    for i in range(nx):
        row = slopes[i, :]
        n_nan = np.sum(np.isnan(row))
        avg_value_at_x[i] = np.nan if n_nan==nslopes else np.nanmean(row)
        slope_counts_at_x[i] = nslopes - n_nan

    # return average slope at each unique x value and how many slopes included in avg at each x
    return avg_value_at_x, slope_counts_at_x


def plot_stratpd_gridsearch(X, y, colname, targetname,
                            min_samples_leaf_values=(2,5,10,20,30),
                            min_slopes_per_x_values=(15,), # Show default count only by default
                            nbins_values=(1,2,3,4,5),
                            nbins_smoothing=None,
                            binned=False,
                            yrange=None,
                            xrange=None,
                            show_regr_line=False,
                            marginal_alpha=.05,
                            slope_line_alpha=.1,
                            title_fontsize=8,
                            label_fontsize=7,
                            ticklabel_fontsize=7,
                            cellwidth=2.5,
                            cellheight=2.5):
    ncols = len(min_samples_leaf_values)
    if not binned:
        fig, axes = plt.subplots(len(min_slopes_per_x_values), ncols + 1,
                                 figsize=((ncols + 1) * cellwidth, len(min_slopes_per_x_values)*cellheight))
        if len(min_slopes_per_x_values)==1:
            axes = axes.reshape(1,-1)
        for row,min_slopes_per_x in enumerate(min_slopes_per_x_values):
            marginal_plot_(X, y, colname, targetname, ax=axes[row][0],
                           show_regr_line=show_regr_line, alpha=marginal_alpha,
                           label_fontsize=label_fontsize,
                           ticklabel_fontsize=ticklabel_fontsize)
            col = 1
            axes[row][0].set_title("Marginal", fontsize=title_fontsize)
            for msl in min_samples_leaf_values:
                #print(f"---------- min_samples_leaf={msl} ----------- ")
                try:
                    leaf_xranges, leaf_slopes, slope_counts_at_x, pdpx, pdpy, ignored = \
                        plot_stratpd(X, y, colname, targetname, ax=axes[row][col],
                                     min_samples_leaf=msl,
                                     min_slopes_per_x=min_slopes_per_x,
                                     xrange=xrange,
                                     yrange=yrange,
                                     ntrees=1,
                                     show_ylabel=False,
                                     slope_line_alpha=slope_line_alpha,
                                     label_fontsize=label_fontsize,
                                     ticklabel_fontsize=ticklabel_fontsize)
                    # print(f"leafsz {msl} avg abs curve value: {np.mean(np.abs(pdpy)):.2f}, mean {np.mean(pdpy):.2f}, min {np.min(pdpy):.2f}, max {np.max(pdpy)}")
                except ValueError as e:
                    print(e)
                    axes[row][col].set_title(f"Can't gen: leafsz={msl}", fontsize=8)
                else:
                    title = f"leafsz={msl}, min_slopes={min_slopes_per_x}"
                    if ignored>0:
                        title = f"leafsz={msl}, min_slopes={min_slopes_per_x},\nignored={100 * ignored / len(X):.2f}%"
                    axes[row][col].set_title(title, fontsize=title_fontsize)
                col += 1

    else:
        # more or less ignoring this branch these days
        nrows = len(nbins_values)
        fig, axes = plt.subplots(nrows, ncols + 1,
                                 figsize=((ncols + 1) * 2.5, nrows * 2.5))

        row = 0
        for i, nbins in enumerate(nbins_values):
            marginal_plot_(X, y, colname, targetname, ax=axes[row, 0], show_regr_line=show_regr_line)
            if row==0:
                axes[row,0].set_title("Marginal", fontsize=10)
            col = 1
            for msl in min_samples_leaf_values:
                #print(f"---------- min_samples_leaf={msl}, nbins={nbins:.2f} ----------- ")
                try:
                    leaf_xranges, leaf_slopes, Xbetas, plot_x, plot_y, ignored = \
                        plot_stratpd_binned(X, y, colname, targetname, ax=axes[row, col],
                                            nbins=nbins,
                                            min_samples_leaf=msl,
                                            nbins_smoothing=nbins_smoothing,
                                            yrange=yrange,
                                            show_ylabel=False,
                                            ntrees=1)
                except ValueError:
                    axes[row, col].set_title(
                        f"Can't gen: leafsz={msl}, nbins={nbins}",
                        fontsize=8)
                else:
                    axes[row, col].set_title(
                        f"leafsz={msl}, nbins={nbins},\nignored={100*ignored/len(X):.2f}%",
                        fontsize=9)
                col += 1
            row += 1


def marginal_plot_(X, y, colname, targetname, ax, alpha=.1, show_regr_line=True,
                   label_fontsize=7,
                   ticklabel_fontsize=7):
    ax.scatter(X[colname], y, alpha=alpha, label=None, s=10)
    ax.set_xlabel(colname, fontsize=label_fontsize)
    ax.set_ylabel(targetname, fontsize=label_fontsize)
    col = X[colname]

    ax.tick_params(axis='both', which='major', labelsize=ticklabel_fontsize)

    if show_regr_line:
        r = LinearRegression()
        r.fit(X[[colname]], y)
        xcol = np.linspace(np.min(col), np.max(col), num=100)
        yhat = r.predict(xcol.reshape(-1, 1))
        ax.plot(xcol, yhat, linewidth=1, c='orange', label=f"$\\beta_{{{colname}}}$")
        ax.text(min(xcol) * 1.02, max(y) * .95, f"$\\beta_{{{colname}}}$={r.coef_[0]:.3f}")


def marginal_catplot_(X, y, colname, targetname, ax, catnames, alpha=.1, show_xticks=True):
    catcodes, catnames_, catcode2name = getcats(X, colname, catnames)

    ax.scatter(X[colname].values, y.values, alpha=alpha, label=None, s=10)
    ax.set_xlabel(colname)
    ax.set_ylabel(targetname)
    # col = X[colname]
    # cats = np.unique(col)

    if show_xticks:
        ax.set_xticks(catcodes)
        ax.set_xticklabels(catnames_)
    else:
        ax.set_xticks([])

def plot_catstratpd_gridsearch(X, y, colname, targetname,
                               min_samples_leaf_values=(2, 5, 10, 20, 30),
                               min_y_shifted_to_zero=True, # easier to read if values are relative to 0 (usually); do this for high cardinality cat vars
                               show_xticks=True,
                               catnames=None,
                               yrange=None,
                               sort='ascending',
                               cellwidth=2.5, 
                               cellheight=2.5):
    ncols = len(min_samples_leaf_values)
    fig, axes = plt.subplots(1, ncols + 1,
                             figsize=((ncols + 1) * cellwidth, cellheight))

    marginal_catplot_(X, y, colname, targetname, catnames=catnames, ax=axes[0], alpha=0.05,
                      show_xticks=show_xticks)
    axes[0].set_title("Marginal", fontsize=10)

    col = 1
    for msl in min_samples_leaf_values:
        #print(f"---------- min_samples_leaf={msl} ----------- ")
        if yrange is not None:
            axes[col].set_ylim(yrange)
        try:
            catcodes_, catnames_, curve, ignored = \
                plot_catstratpd(X, y, colname, targetname, ax=axes[col],
                                min_samples_leaf=msl,
                                catnames=catnames,
                                yrange=yrange,
                                ntrees=1,
                                show_xticks=show_xticks,
                                show_ylabel=False,
                                sort=sort,
                                min_y_shifted_to_zero=min_y_shifted_to_zero)
        except ValueError:
            axes[col].set_title(f"Can't gen: leafsz={msl}", fontsize=8)
        else:
            axes[col].set_title(f"leafsz={msl}, ign'd={ignored / len(X):.1f}%", fontsize=9)
        col += 1


def catwise_leaves(rf, X_not_col, X_col, y):
    """
    Return a 2D array with the average y value for each category in each leaf
    normalized by subtracting min avg y value from all categories.
    The columns are the y avg value changes found in a single leaf.
    Each row represents a category level. E.g.,

    row           leaf0       leaf1
     0       166.430176  186.796956
     1       219.590349  176.448626
    """
    leaves = leaf_samples(rf, X_not_col)

    leaf_histos = np.full(shape=(max(X_col)+1, len(leaves)), fill_value=np.nan)
    ignored = 0
    for leaf_i in range(len(leaves)):
        sample = leaves[leaf_i]
        leaf_cats = X_col[sample]
        leaf_y = y[sample]
        uniq_cats = np.unique(leaf_cats)
        avg_y_per_cat = np.array([leaf_y[leaf_cats==cat].mean() for cat in uniq_cats])
        if len(avg_y_per_cat) < 2:
            # print(f"ignoring {len(sample)} obs for {len(avg_y_per_cat)} cat(s) in leaf")
            ignored += len(sample)
            continue

        # record avg y value per cat above avg y in this leaf
        # leave cats w/o representation as nan
        avg_leaf_y = np.mean(leaf_y)
        delta_y_per_cat = avg_y_per_cat - avg_leaf_y
        leaf_histos[uniq_cats, leaf_i] = delta_y_per_cat

    return leaf_histos, ignored


def cat_partial_dependence(X, y,
                           colname,  # X[colname] expected to be numeric codes
                           n_trees=1,
                           min_samples_leaf=10,
                           max_features=1.0,
                           bootstrap=False,
                           supervised=True,
                           use_weighted_avg=False,  # not implemented
                           verbose=False):
    X_not_col = X.drop(colname, axis=1).values
    X_col = X[colname].values
    if supervised:
        rf = RandomForestRegressor(n_estimators=n_trees,
                                   min_samples_leaf=min_samples_leaf,
                                   bootstrap = bootstrap,
                                   max_features = max_features,
                                   oob_score=False)
        rf.fit(X_not_col, y)
        if verbose:
            print(f"CatStrat Partition RF: dropping {colname} training R^2 {rf.score(X_not_col, y):.2f}")
    else:
        print("USING UNSUPERVISED MODE")
        X_synth, y_synth = conjure_twoclass(X)
        rf = RandomForestRegressor(n_estimators=n_trees,
                                   min_samples_leaf=min_samples_leaf,
                                   bootstrap = bootstrap,
                                   max_features = max_features,
                                   oob_score=False)
        rf.fit(X_synth.drop(colname,axis=1), y_synth)

    # rf = RandomForestRegressor(n_estimators=ntrees, min_samples_leaf=min_samples_leaf, oob_score=True)
    rf.fit(X_not_col, y)
    # print(f"Model wo {colname} OOB R^2 {rf.oob_score_:.5f}")
    # leaf_histos, leaf_avgs, leaf_sizes, leaf_catcounts, ignored = \
    #     catwise_leaves(rf, X, y, colname, verbose=verbose)

    leaf_histos, ignored = \
        catwise_leaves(rf, X_not_col, X_col, y.values)

    if verbose:
        print(f"CatStratPD Num samples ignored {ignored} for {colname}")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        avg_per_cat = np.nanmean(leaf_histos, axis=1)
        # slope_counts_at_cat = leaf_histos.shape[1] - np.isnan(leaf_histos).sum(axis=1)

    # print("slope_counts_at_cat", colname, list(slope_counts_at_cat)[:100])
    # print("avg_per_cat", colname, list(avg_per_cat)[:100])

    return leaf_histos, avg_per_cat, ignored


# only works for ints, not floats
def plot_catstratpd(X, y,
                    colname,  # X[colname] expected to be numeric codes
                    targetname,
                    catnames=None,  # map of catcodes to catnames; converted to map if sequence passed
                    # must pass dict or series if catcodes are not 1..n contiguous
                    # None implies use np.unique(X[colname]) values
                    # Must be 0-indexed list of names if list
                    ax=None,
                    sort='ascending',
                    ntrees=1,
                    min_samples_leaf=10,
                    max_features=1.0,
                    bootstrap=False,
                    yrange=None,
                    title=None,
                    supervised=True,
                    use_weighted_avg=False,
                    alpha=.15,
                    color='#2c7fb8',
                    pdp_marker_size=.5,
                    marker_size=5,
                    pdp_color='black',
                    style:('strip','scatter')='strip',
                    min_y_shifted_to_zero=True, # easier to read if values are relative to 0 (usually); do this for high cardinality cat vars
                    show_xlabel=True,
                    show_ylabel=True,
                    show_xticks=True,
                    verbose=False):
    """
    Warning: cat columns are assumed to be label encoded as unique integers. This
    function uses the cat code as a raw index internally. So if you have two cat
    codes 1 and 1000, this function allocates internal arrays of size 1000+1.

    :param X:
    :param y:
    :param colname:
    :param targetname:
    :param catnames:
    :param ax:
    :param sort:
    :param ntrees:
    :param min_samples_leaf:
    :param max_features:
    :param bootstrap:
    :param yrange:
    :param title:
    :param supervised:
    :param use_weighted_avg:
    :param alpha:
    :param color:
    :param pdp_marker_size:
    :param marker_size:
    :param pdp_color:
    :param style:
    :param min_y_shifted_to_zero:
    :param show_xlabel:
    :param show_ylabel:
    :param show_xticks:
    :param verbose:
    :return:
    """

    catcodes, _, catcode2name = getcats(X, colname, catnames)

    leaf_histos, avg_per_cat, ignored = \
        cat_partial_dependence(X, y,
                               colname=colname,
                               n_trees=ntrees,
                               min_samples_leaf=min_samples_leaf,
                               max_features=max_features,
                               bootstrap=bootstrap,
                               supervised=supervised,
                               use_weighted_avg=use_weighted_avg,
                               verbose=verbose)

    if ax is None:
        fig, ax = plt.subplots(1, 1)

    ncats = len(catcodes)
    nleaves = leaf_histos.shape[1]

    sorted_catcodes = catcodes
    if sort == 'ascending':
        sorted_indexes = avg_per_cat[~np.isnan(avg_per_cat)].argsort()
        sorted_catcodes = catcodes[sorted_indexes]
    elif sort == 'descending':
        sorted_indexes = avg_per_cat.argsort()[::-1]  # reversed
        sorted_catcodes = catcodes[sorted_indexes]

    min_avg_value = 0
    # The category y deltas straddle 0 but it's easier to understand if we normalize
    # so lowest y delta is 0
    if min_y_shifted_to_zero:
        min_avg_value = np.nanmin(avg_per_cat)

    # print(leaf_histos.iloc[np.nonzero(catcounts)])
    # # print(leaf_histos.notna().multiply(leaf_sizes, axis=1))
    # # print(np.sum(leaf_histos.notna().multiply(leaf_sizes, axis=1), axis=1))
    # print(f"leaf_sizes: {list(leaf_sizes)}")
    # print(f"weighted_sum_per_cat: {list(weighted_sum_per_cat[np.nonzero(weighted_sum_per_cat)])}")
    # # print(f"catcounts: {list(catcounts[np.nonzero(catcounts)])}")
    # # print(f"Avg per cat: {list(avg_per_cat[np.nonzero(catcounts)]-min_avg_value)}")
    # print(f"Avg per cat: {list(avg_per_cat[~np.isnan(avg_per_cat)]-min_avg_value)}")

    # if too many categories, can't do strip plot
    xloc = 0
    sigma = .02
    mu = 0
    if style == 'strip':
        x_noise = np.random.normal(mu, sigma, size=nleaves) # to make strip plot
    else:
        x_noise = np.zeros(shape=(nleaves,))
    for cat in sorted_catcodes:
        if catcode2name[cat] is None: continue
        ax.scatter(x_noise + xloc, leaf_histos[catcode2name[cat]] - min_avg_value,
                   alpha=alpha, marker='o', s=marker_size,
                   c=color)
        if style == 'strip':
            ax.plot([xloc - .1, xloc + .1], [avg_per_cat[catcode2name[cat]]-min_avg_value] * 2,
                    c='black', linewidth=2)
        else:
            ax.scatter(xloc, avg_per_cat[catcode2name[cat]]-min_avg_value, c=pdp_color, s=pdp_marker_size)
        xloc += 1

    ax.set_xticks(range(0, ncats))
    if show_xticks: # sometimes too many
        ax.set_xticklabels(catcode2name[sorted_catcodes])
    else:
        ax.set_xticklabels([])
        ax.tick_params(axis='x', which='both', bottom=False)

    if show_xlabel:
        ax.set_xlabel(colname)
    if show_ylabel:
        ax.set_ylabel(targetname)
    if title is not None:
        ax.set_title(title)

    if yrange is not None:
        ax.set_ylim(*yrange)

    ycats = avg_per_cat[sorted_catcodes] - min_avg_value
    return catcodes, catcode2name[sorted_catcodes], ycats, ignored


def getcats(X, colname, incoming_cats):
    if incoming_cats is None or isinstance(incoming_cats, pd.Series):
        catcodes = np.unique(X[colname])
        catcode2name = [None] * (max(catcodes) + 1)
        for c in catcodes:
            catcode2name[c] = c
        catcode2name = np.array(catcode2name)
        catnames = catcodes
    elif isinstance(incoming_cats, dict):
        catnames_ = [None] * (max(incoming_cats.keys()) + 1)
        catcodes = []
        catnames = []
        for code, name in incoming_cats.items():
            catcodes.append(code)
            catnames.append(name)
            catnames_[code] = name
        catcodes = np.array(catcodes)
        catnames = np.array(catnames)
        catcode2name = np.array(catnames_)
    elif not isinstance(incoming_cats, dict):
        # must be a list of names then
        catcodes = []
        catnames_ = [None] * len(incoming_cats)
        for cat, c in enumerate(incoming_cats):
            if c is not None:
                catcodes.append(cat)
            catnames_[cat] = c
        catcodes = np.array(catcodes)
        catcode2name = np.array(catnames_)
        catnames = np.array(incoming_cats)
    else:
        raise ValueError("catnames must be None, 0-indexed list, or pd.Series")
    return catcodes, catnames, catcode2name


# -------------- S U P P O R T ---------------


def scramble(X : np.ndarray) -> np.ndarray:
    """
    From Breiman: https://www.stat.berkeley.edu/~breiman/RandomForests/cc_home.htm
    "...the first coordinate is sampled from the N values {x(1,n)}. The second
    coordinate is sampled independently from the N values {x(2,n)}, and so forth."
    """
    X_rand = X.copy()
    ncols = X.shape[1]
    for col in range(ncols):
        # TODO: whoa. shouldn't be unique() should it?
        X_rand[:,col] = np.random.choice(np.unique(X[:,col]), len(X), replace=True)
    return X_rand


def df_scramble(X : pd.DataFrame) -> pd.DataFrame:
    """
    From Breiman: https://www.stat.berkeley.edu/~breiman/RandomForests/cc_home.htm
    "...the first coordinate is sampled from the N values {x(1,n)}. The second
    coordinate is sampled independently from the N values {x(2,n)}, and so forth."
    """
    X_rand = X.copy()
    for colname in X:
        # TODO: whoa. shouldn't be unique() should it?
        X_rand[colname] = np.random.choice(X[colname].unique(), len(X), replace=True)
    return X_rand


def conjure_twoclass(X):
    """
    Make new data set 2x as big with X and scrambled version of it that
    destroys structure between features. Old is class 0, scrambled is class 1.
    """
    if isinstance(X, pd.DataFrame):
        X_rand = df_scramble(X)
        X_synth = pd.concat([X, X_rand], axis=0)
    else:
        X_rand = scramble(X)
        X_synth = np.concatenate([X, X_rand], axis=0)
    y_synth = np.concatenate([np.zeros(len(X)),
                              np.ones(len(X_rand))], axis=0)
    return X_synth, pd.Series(y_synth)
