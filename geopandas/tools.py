from shapely.ops import unary_union, polygonize
from shapely.geometry import MultiLineString
import pandas as pd
from geopandas import GeoDataFrame, GeoSeries

def _extract_rings(df):
    """Collects all inner and outer linear rings from a GeoDataFrame 
    with (multi)Polygon geometeries

    Parameters
    ----------
    df: GeoDataFrame with MultiPolygon or Polygon geometry column

    Returns
    -------
    rings: list of LinearRings
    """
    poly_msg = "overlay only takes GeoDataFrames with (multi)polygon geometries"
    rings = []
    for i, feat in df.iterrows():
        geom = feat.geometry

        if geom.type not in ['Polygon', 'MultiPolygon']:
            raise TypeError(poly_msg)

        if hasattr(geom, 'geoms'):
            for poly in geom.geoms:  # if it's a multipolygon
                if not poly.is_valid:
                    # geom from layer is not valid attempting fix by buffer 0"
                    poly = poly.buffer(0)
                rings.append(poly.exterior)
                rings.extend(poly.interiors)
        else:
            if not geom.is_valid:
                # geom from layer is not valid attempting fix by buffer 0"
                geom = geom.buffer(0)
            rings.append(geom.exterior)
            rings.extend(geom.interiors)

    return rings

def overlay(df1, df2, how):
    """Perform spatial overlay between two polygons
    Currently only supports data GeoDataFrames with polygons

    Implements several methods (see `allowed_hows` list) that are
    all effectively subsets of the union.
    """
    allowed_hows = [
        'intersection',
        'union',
        'identity',
        'symmetric_difference',
        'difference',  # aka erase
    ]

    if how not in allowed_hows:
        raise ValueError("`how` was \"%s\" but is expected to be in %s" % \
            (how, allowed_hows))

    # Collect the interior and exterior rings
    rings1 = _extract_rings(df1)
    rings2 = _extract_rings(df2)
    mls1 = MultiLineString(rings1)
    mls2 = MultiLineString(rings2)

    # Union and polygonize
    try:
        # calculating union (try the fast unary_union)
        mm = unary_union([mls1, mls2])
    except:
        # unary_union FAILED
        # see https://github.com/Toblerity/Shapely/issues/47#issuecomment-18506767
        # calculating union again (using the slow a.union(b))
        mm = mls1.union(mls2)
    newpolys = polygonize(mm)

    # determine spatial relationship
    collection = []
    for fid, newpoly in enumerate(newpolys):
        cent = newpoly.representative_point()

        # Test intersection with original polys
        # TODO use spatial index
        candidates1 = df1.iterrows()
        candidates2 = df2.iterrows()
        df1_hit = False
        df2_hit = False
        prop1 = None
        prop2 = None
        for i, cand in candidates1:
            if cent.intersects(cand['geometry']):
                df1_hit = True
                prop1 = cand
                break
        for i, cand in candidates2:
            if cent.intersects(cand['geometry']):
                df2_hit = True
                prop2 = cand
                break

        # determine spatial relationship based on type of overlay
        hit = False
        if how == "intersection" and (df1_hit and df2_hit):
            hit = True
        elif how == "union" and (df1_hit or df2_hit):
            hit = True
        elif how == "identity" and df1_hit:
            hit = True
        elif how == "symmetric_difference" and not (df1_hit and df2_hit):
            hit = True
        elif how == "difference" and (df1_hit and not df2_hit):
            hit = True

        if not hit:
            continue

        # gather properties
        if prop1 is None:
            prop1 = pd.Series(dict.fromkeys(df1.columns, None))
        if prop2 is None:
            prop2 = pd.Series(dict.fromkeys(df2.columns, None))
        out_series = pd.concat([prop1, prop2])
        
        # Don't retain the original geometries
        out_series.drop(df1._geometry_column_name, inplace=True)
        try:
            out_series.drop(df2._geometry_column_name, inplace=True)
        except ValueError:
            pass  # the geometry column might have been wiped by first call

        # Create a geoseries and add it to the collection
        out_series['geometry'] = newpoly
        # FIXME is there a more idomatic way to append a geometry to a Series 
        # and get a GeoSeries back? 
        out_series.__class__ = GeoSeries
        out_series._geometry_column_name = 'geometry'
        collection.append(out_series)

    # Create geodataframe, clean up indicies and return it
    gdf = GeoDataFrame(collection).reset_index()
    gdf.drop('index', axis=1, inplace=True)
    return gdf
