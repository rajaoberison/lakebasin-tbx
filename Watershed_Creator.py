# -*- coding: utf-8 -*-
import sys
import os
import arcpy
import traceback

from cookielib import CookieJar
import urllib2
import wget
import zipfile

arcpy.env.overwriteOutput = True

# Login into EarthData for DEM download
# Adapted from https://wiki.earthdata.nasa.gov/display/EL/How+To+Access+Data+With+Python
# The user credentials that will be used to authenticate access to the data
username = arcpy.GetParameterAsText(3)
password = arcpy.GetParameterAsText(4)

# Create a password manager to deal with the 401 response that is returned from
# EarthData Login
password_manager = urllib2.HTTPPasswordMgrWithDefaultRealm()
password_manager.add_password(None, "https://urs.earthdata.nasa.gov", username, password)

# Create a cookie jar for storing cookies. This is used to store and return
# the session cookie given to use by the data server (otherwise it will just
# keep sending us back to EarthData Login to authenticate).  Ideally, we
# should use a file based cookie jar to preserve cookies between runs. This
# will make it much more efficient.
cookie_jar = CookieJar()

# Install all the handlers.
opener = urllib2.build_opener(
    urllib2.HTTPBasicAuthHandler(password_manager),
    urllib2.HTTPCookieProcessor(cookie_jar))
urllib2.install_opener(opener)


# Check to see if Spatial Analyst license is available
if arcpy.CheckExtension("spatial") == "Available":

    # Activate ArcGIS Spatial Analyst license
    arcpy.CheckOutExtension("spatial")

    # User inputs from dialog box
    pour_points = arcpy.GetParameterAsText(0)
    pour_points_unique_id = arcpy.GetParameterAsText(1)

    # Workspace
    workspace = arcpy.GetParameterAsText(2)
    # lakes = arcpy.Raster(arcpy.GetParameterAsText(5))
    lakes = arcpy.GetParameterAsText(5)
    # arcpy.env.snapRaster = arcpy.GetParameterAsText(6)
    arcpy.env.workspace = workspace

    study_reg = arcpy.Describe(pour_points).extent
    study_extent = "{0} {1} {2} {3}".format(study_reg.XMin-1, study_reg.YMin-1,
                                            study_reg.XMax+1, study_reg.YMax+1)
    # arcpy.env.extent = study_extent_values
    arcpy.env.pyramid = "NONE"


    # Spatial reference of points
    sr = arcpy.Describe(pour_points).spatialReference

    # Extract DEM data online
    # Coordinates of pour points
    arcpy.AddGeometryAttributes_management(pour_points, "POINT_X_Y_Z_M")
    sites = [[r[0], r[1], r[2]] for r in arcpy.da.SearchCursor(pour_points,
                                                               ["POINT_X", "POINT_Y", pour_points_unique_id])]

    # # Creating empty shapefile to store the results
    # watersheds = arcpy.CreateFeatureclass_management(arcpy.env.workspace, 'watersheds.shp', "POLYGON",
    #                                                  spatial_reference=sr)
    # arcpy.AddField_management(watersheds, pour_points_unique_id, "SHORT")
    # mxd = arcpy.mapping.MapDocument("CURRENT")
    # df = arcpy.mapping.ListDataFrames(mxd, "*")[0]
    # arcpy.env.extent = df.extent


    watersheds = arcpy.CreateFeatureclass_management(arcpy.env.workspace, 'watersheds.shp', "POLYGON",
                                                     spatial_reference=sr)
    arcpy.AddField_management(watersheds, 'id_site', "SHORT")

    # Where there might be issues
    error_points = open(os.path.join(arcpy.env.workspace, "error_points.txt"), "a")

    # Creating watersheds for each point
    for a_site in sites:
        try:
            arcpy.env.extent = study_extent
            # arcpy.AddMessage('st_extent %s' % arcpy.env.extent)

            arcpy.AddMessage("\nProcessing Site {0}".format(a_site[2]))
            # Point data
            this_point = arcpy.PointGeometry(arcpy.Point(a_site[0], a_site[1]), sr)
            arcpy.CopyFeatures_management(this_point, "this_point.shp")
            arcpy.AddField_management("this_point.shp", pour_points_unique_id, "SHORT")
            arcpy.CalculateField_management("this_point.shp", pour_points_unique_id, "{0}".format(a_site[2]))

            # Region needing DEM
            arcpy.Buffer_analysis("this_point.shp", "region.shp", "0.1 Unknown")

            # mxd = arcpy.mapping.MapDocument("CURRENT")
            # df = arcpy.mapping.ListDataFrames(mxd, "*")[0]
            # layer = arcpy.mapping.Layer( "region.shp")
            # arcpy.mapping.AddLayer(df, layer)

            reg_extent = arcpy.Describe("region.shp").extent
            buffer=1
            extent_0 = "{0} {1} {2} {3}".format(reg_extent.XMin-buffer, reg_extent.YMin-buffer,
                                                reg_extent.XMax+buffer, reg_extent.YMax+buffer)
            extent = "{0} {1} {2} {3}".format(reg_extent.XMin, reg_extent.YMin, reg_extent.XMax,
                                              reg_extent.YMax)
            arcpy.env.extent = extent_0
            arcpy.AddMessage('reg_extent %s' % extent)

            bounds_X = list(set([int(math.floor(reg_extent.XMin)), int(math.floor(reg_extent.XMax))]))
            bounds_Y = list(set([int(math.floor(reg_extent.YMin)), int(math.floor(reg_extent.YMax))]))
            arcpy.AddMessage('x %s y %s' % (bounds_X, bounds_Y))

            arcpy.AddMessage('Getting DEM')

            for a_long in bounds_X:
                for a_lat in bounds_Y:

                    # Getting the raw dem
                    # tile_left = int(math.floor(a_site[0]))      # lower longitude
                    # tile_bottom = int(math.floor(a_site[1]))    # lower latitude

                    tile_left = a_long      # lower longitude
                    tile_bottom = a_lat    # lower latitude

                    if len(str(abs(tile_left))) == 1:
                        prefix_lon = "00"
                    elif len(str(abs(tile_left))) == 2:
                        prefix_lon = "0"
                    else:
                        prefix_lon = ""
                    if len(str(abs(tile_bottom))) == 1:
                        prefix_lat = "0"
                    else:
                        prefix_lat = ""

                    if tile_left < 0:
                        tile_left_E = "W%s%s" % (prefix_lon, abs(tile_left))
                    else:
                        tile_left_E = "E%s%s" % (prefix_lon, abs(tile_left))
                    if tile_bottom < 0:
                        tile_bottom_N = "S%s%s" % (prefix_lat, abs(tile_bottom))
                    else:
                        tile_bottom_N = "N%s%s" % (prefix_lat, abs(tile_bottom))

                    # arcpy.AddMessage("tile_left_E: %s, tile_bottom_N: %s" % (tile_left_E, tile_bottom_N))

                    # Downloading dem
                    url = "http://e4ftl01.cr.usgs.gov/MEASURES/SRTMGL1.003/2000.02.11/{0}{1}.SRTMGL1.hgt.zip".format(
                        tile_bottom_N, tile_left_E)
                    # arcpy.AddMessage("Downloading {0}{1}.SRTMGL1.hgt.zip  url: {2}".format(tile_bottom_N, tile_left_E,
                    #                                                                        url))
                    path_to_zip = os.path.join(workspace, "{0}{1}.SRTMGL1.hgt.zip".format(
                        tile_bottom_N, tile_left_E))

                    # Sending requests
                    request = urllib2.Request(url)
                    response = urllib2.urlopen(request)
                    zip_content = response.read()

                    with open(path_to_zip, 'wb') as raw_zip:  # only the binary writing mode worked
                        raw_zip.write(zip_content)
                    raw_zip.close()

                    # Extracting zip file
                    zip_ref = zipfile.ZipFile(path_to_zip, 'r')
                    zip_ref.extractall(workspace)
                    zip_ref.close()

            # Path to the extracted dem
            # path_to_dem = os.path.join(arcpy.env.workspace, "{0}{1}.hgt".format(tile_bottom_N, tile_left_E))

            # Mosaic to New raster
            dem_list = [os.path.join(workspace, f) for f in os.listdir(workspace) if f.endswith(".hgt")]
            arcpy.AddMessage(dem_list)
            if len(dem_list) == 1:
                path_to_dem = dem_list[0]
            else:
                arcpy.MosaicToNewRaster_management(
                    dem_list, workspace, 'mosaic_%s' % a_site[2], number_of_bands=1)
                path_to_dem = 'mosaic_%s' % a_site[2]

            # dem_lyr = arcpy.MakeRasterLayer_management(path_to_dem, 'dem_lyr')
            # arcpy.mapping.AddLayer(df, dem_lyr.getOutput(0))

            # Watershed Delineation
            # Clip raster
            clipped_dem = arcpy.Clip_management(path_to_dem, extent, "clipped_dem.tif",
                                                in_template_dataset="region.shp",
                                                clipping_geometry="ClippingGeometry")
            resampled_dem = arcpy.Resample_management(clipped_dem, 'resampled_dem.tif', 0.0003)
            arcpy.env.snapRaster = 'resampled_dem.tif'

            arcpy.AddMessage('Hydrology operation')
            # Fill operation
            filled_dem = arcpy.sa.Fill(in_surface_raster=resampled_dem)

            # Flow direction
            flow_direction = arcpy.sa.FlowDirection(in_surface_raster=filled_dem, flow_direction_type="D8")
            flow_direction = arcpy.sa.Int(flow_direction)
            # flow_direction.save('fdir.tif')

            arcpy.AddMessage('Lake to raster')
            arcpy.MakeFeatureLayer_management("this_point.shp", "this_point_lyr")
            arcpy.MakeFeatureLayer_management(lakes, "lakes_lyr")
            arcpy.SelectLayerByLocation_management('lakes_lyr', 'INTERSECT', 'this_point_lyr',
                                                   selection_type='NEW_SELECTION')
            this_lake = arcpy.CopyFeatures_management('lakes_lyr', 'this_lake.shp')

            # arcpy.env.extent = extent
            lake_raster = arcpy.PolygonToRaster_conversion(this_lake, 'FID', 'lake_%s.tif' % a_site[2],
                                                cellsize=0.0003)

            raster_watersheds = arcpy.sa.Watershed(in_flow_direction_raster=flow_direction,
                                                   in_pour_point_data=lake_raster)
            # raster_watersheds.save('w_%s' % a_site)

            # Converting the watershed raster into polygons
            arcpy.RasterToPolygon_conversion(in_raster=raster_watersheds,
                                             out_polygon_features='wtrshd.shp',
                                             simplify="SIMPLIFY")
            # Adding ID to the watersheds
            arcpy.AddField_management('wtrshd.shp', 'id_site', "SHORT")
            arcpy.CalculateField_management('wtrshd.shp', 'id_site', "{0}".format(a_site[2]))
            arcpy.DeleteField_management('wtrshd.shp', ["GRIDCODE"])

            arcpy.env.workspace = workspace

            # Saving all watersheds in one shapefile
            arcpy.Append_management('wtrshd.shp', watersheds)


            # Deleting unnecessary files
            arcpy.Delete_management(filled_dem)
            arcpy.Delete_management(path_to_dem)
            arcpy.Delete_management(lake_raster)
            arcpy.Delete_management(resampled_dem)
            arcpy.Delete_management("region.shp")
            arcpy.Delete_management("this_point.shp")
            arcpy.Delete_management(clipped_dem)
            # arcpy.Delete_management('wtrshd_{0}'.format(a_site[2]))
            # arcpy.Delete_management('this_lake')

            for f in os.listdir(arcpy.env.workspace):
                if f.endswith(".zip") or f.endswith(".hgt"):
                    arcpy.Delete_management(f)

            # for f in os.listdir(workspace):
            #     if f not in ['error_points.txt', 'watersheds.shp', 'watersheds.dbf', 'watersheds.prj',
            #                  'watersheds.cpg', 'watersheds.shx', 'watersheds.shp.xml']:
            #         arcpy.Delete_management(f)

        except Exception as e:
            # If unsuccessful, end gracefully by indicating why
            arcpy.AddError('\n' + "Script failed because: \t\t" + e.message)
            # ... and where
            exception_report = sys.exc_info()[2]
            fuller_message = traceback.format_tb(exception_report)[0]
            arcpy.AddError("at this location: \n\n" + fuller_message + "\n")

            error_points.write(str(a_site[2]) + "\n")
            continue

    error_points.close()



    # Deactivate ArcGIS Spatial Analyst license
    # arcpy.CheckInExtension("spatial")

else:
    # Report error message if Spatial Analyst license is unavailable
    arcpy.AddMessage("Spatial Analyst license is unavailable")
