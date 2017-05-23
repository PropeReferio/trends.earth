# -*- coding: utf-8 -*-
"""
/***************************************************************************
 LDMP
                                 A QGIS plugin
 This plugin supports monitoring and reporting of land degradation to the UNCCD and in support of the SDG Land Degradation Neutrality (LDN) target
                             -------------------
        begin                : 2017-05-23
        copyright            : (C) 2017 by Conservation International
        email                : GEF-LDMP@conservation.org
        git sha              : $Format:%H$
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
 This script initializes the plugin, making it known to QGIS.
"""


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load LDMP class from file LDMP.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    #
    from .ldmp import LDMP
    return LDMP(iface)
