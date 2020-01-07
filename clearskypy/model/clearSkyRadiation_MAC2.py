import numpy as np
import os
from ..extractor.extract import extract_dataset_list, extract_dataset
from .solarGeometry import *


class ClearSkyMac:

    def __init__(self, lat: np.ndarray, lon: np.ndarray, elev, time, datadir='./MERRA2_data/'):
        if lat.shape != lon.shape:
            raise Exception('lat and lon not match...')
        if np.max(np.abs(lat)) > 90:
            raise Exception('90<= lattitude <=90, reset your latitude')
        if np.max(np.abs(lon)) > 180:
            raise Exception('-180<= lontitude <=180, reset your lontitude')

        station_num = np.size(lat, 0)
        self.lat = lat.reshape([station_num, ])
        self.lon = lon.reshape([station_num, ])
        self.elev = elev.reshape([station_num, 1])
        self.time = time
        self.datadir = datadir

    def collect_data(self):
        datadir = self.datadir
        datadirlist = [os.listdir(datadir)][0]
        dirlist = []
        asmlist = []
        for file in datadirlist:
            if 'index' in file:
                continue
            elif 'const_2d_asm' in file:
                asmlist.append(datadir + file)
            elif 'merra2' in file:
                dirlist.append(datadir + file)
        variables = ['TOTEXTTAU', 'TOTSCATAU', 'TOTANGSTR', 'ALBEDO', 'TO3', 'TQV', 'PS']
        [AOD_550, tot_aer_ext, tot_angst, albedo, ozone, water_vapour, pressure] = extract_dataset_list(self.lat,
                                                                                                        self.lon,
                                                                                                        dirlist,
                                                                                                        variables,
                                                                                                        self.time,
                                                                                                        interpolate=True)
        [phis] = extract_dataset(self.lat, self.lon, asmlist[0], ['PHIS'], self.time, interpolate=False)

        water_vapour = water_vapour * 0.1
        ozone = ozone * 0.001
        h = phis / 9.80665
        h0 = self.elev
        Ha = 2100
        scale_height = np.exp((h0 - h) / Ha)
        AOD_550 = AOD_550 * scale_height.T
        water_vapour = water_vapour * scale_height.T
        tot_angst[tot_angst < 0] = 0

        # initial no2 default 0.0002
        nitrogen_dioxide = np.tile(np.linspace(0.0002, 0.0002, self.time.size).reshape([self.time.size, 1]),
                                   self.lat.size)
        return [tot_aer_ext, AOD_550, tot_angst, ozone, albedo, water_vapour, pressure, nitrogen_dioxide]

    def clear_sky_mac2(self, sza, earth_radius, pressure, wv, ang_beta, ang_alpha, albedo, components):
        """
        clear_sky_model mac2 1982

        Every Variable Need to be np.ndarry. np.matrix will cause fatal error

        ASSUMPTION: all data is in 1-min resolution and all vectors(size: n*1)
        perfectly match each other in terms of time stamps.

        sza   = Zenith angle in degrees. Corresponding to all inputs.
        Earth_radius = Earth heliocentric radius(AU). Eext=Esc*Earth_radius^-2.
        pressure = Local barometric pressure in [mb].
        wv = Total precipitable water vapour in [cm].
        ang_beta = Angstrom turbidity coefficient ¦Â.
        ang_alpha = Angstrom exponent ¦Á.
        albedo = Ground albedo.

        components = 1, output = Edn
        components = 2, output = [Edn, Edh]
        components = 3, output = [Egh, Edn, Edh]

        matlab version coded by Xixi Sun according to Davies and Mckay 1982 <Estimating solar irradiance and components>
        """
        sza[sza > 90] = np.nan
        datapoints = np.size(sza, 0) * np.size(sza, 1)
        # Extraterrestrial irradiance
        esc = 1353  # author set 1353
        eext = esc * np.power(earth_radius, -2)
        # Air Mass
        amm = 35 / np.power((1224 * np.power(np.cos(np.deg2rad(sza)), 2) + 1), 0.5)
        amm[amm < 0] = 0

        # Ozone Transmittance
        ozone = 0.35  # Davies and Mckay 1982 set ozone a fixed value of 3.5mm
        xo = amm * (ozone * 10)  # Davies and Mckay 1982 ozone unit is mm, here in the code unit is cm
        ao = ((0.1082 * xo) / (np.power((1 + 13.86 * xo), 0.805))) + (
                (0.00658 * xo) / (1 + np.power((10.36 * xo), 3))) + (
                     0.002118 * xo / (1 + 0.0042 * xo + 3.23e-6 * np.power(xo, 2)))
        to = 1 - ao

        # Rayleigh Transmittance  (linear interpolation based on  Table 2 in Davies and Mckay 1982 )
        tr = amm
        ammbasis = amm.reshape((datapoints, 1), order='F')
        amms = np.array([0.5, 1, 1.2, 1.4, 1.6, 1.8, 2.0, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6, 10, 30]).reshape(16, 1)
        t_rs = np.array(
            [.9385, .8973, .8830, .8696, .8572, .8455, .8344, .7872, .7673, .7493, .7328, .7177, .7037, .6907, .6108,
             .4364]).reshape(16, 1)
        tr = np.interp(ammbasis[:, 0], amms[:, 0], t_rs[:, 0])
        tr = tr.reshape(np.size(sza, 0), np.size(sza, 1), order='F')

        # Aerosols Transmittance, borrowed from BH 1981
        t_a = ang_beta * (np.power(0.38, -ang_alpha) * 0.2758 + np.power(0.5, -ang_alpha) * 0.35)
        TA = np.exp(-t_a * amm)

        # Water Vapor Transmittance
        xw = amm * wv * 10 * np.power((pressure / 1013.25), 0.75)
        aw = 0.29 * xw / (np.power((1 + 14.15 * xw), 0.635) + 0.5925 * xw)
        # Forward Scatter
        szajiao = sza.reshape((datapoints, 1), order='F')
        szajiaos = np.array([0, 25.8, 36.9, 45.6, 53.1, 60.0, 66.4, 72.5, 78.5, 90]).reshape(10, 1)
        fs = np.array([.92, .91, .89, .86, .83, .78, .71, .67, .60, .60]).reshape(10, 1)
        f = np.interp(szajiao[:, 0], szajiaos[:, 0], fs[:, 0])
        f = f.reshape(np.size(sza, 0), np.size(sza, 1), order='F')

        lower = 0
        if components == 1:
            # Direct normal irradiance
            EbnMAC2 = eext * (to * tr - aw) * TA
            EbnMAC2[EbnMAC2 < lower] = lower  # Quality control

            output = EbnMAC2
        elif components == 2:
            # Direct normal irradiance
            EbnMAC2 = eext * (to * tr - aw) * TA
            EbnMAC2[EbnMAC2 < lower] = lower  # Quality control

            # Diffuse horizontal irradiance
            # diffuse components from Rayleigh scatter
            DR = eext * np.cos(np.deg2rad(sza)) * to * (1 - tr) / 2
            # diffuse components from scattering by aerosol
            DA = eext * np.cos(np.deg2rad(sza)) * (to * tr - aw) * (
                    1 - TA) * 0.75 * f  # w0 = 0.75 according to Table5 in Davies and Mckay 1982
            # diffuse horizontal irradiance
            Taaa = np.power(0.95,
                            1.66)  # Taaa is TA determined at amm=1.66, k=0.95 according to Table5 in Davies and Mckay 1982
            poub = 0.0685 + (1 - Taaa) * 0.75 * (
                    1 - 0.83)  # f' is f determined at amm=1.66, f' equals  0.83, estimate theta when amm=1.66,
            # theta near 53 degree
            EdhMAC2 = poub * albedo * (EbnMAC2 * np.cos(np.deg2rad(sza)) + DR + DA) / (1 - poub * albedo) + DR + DA
            EdhMAC2[EdhMAC2 < lower] = lower  # Quality control

            output = [EbnMAC2, EdhMAC2]
        else:
            # Direct normal irradiance
            EbnMAC2 = eext * (to * tr - aw) * TA
            EbnMAC2[EbnMAC2 < lower] = lower  # Quality control

            # Diffuse horizontal irradiance
            # diffuse components from Rayleigh scatter
            DR = eext * np.cos(np.deg2rad(sza)) * to * (1 - tr) / 2
            # diffuse components from scattering by aerosol
            DA = eext * np.cos(np.deg2rad(sza)) * (to * tr - aw) * (
                    1 - TA) * 0.75 * f  # w0 = 0.75 according to Table5 in Davies and Mckay 1982
            # diffuse horizontal irradiance
            Taaa = np.power(0.95,
                            1.66)  # Taaa is TA determined at amm=1.66, k=0.95 according to Table5 in Davies and Mckay 1982
            poub = 0.0685 + (1 - Taaa) * 0.75 * (
                    1 - 0.83)  # f' is f determined at amm=1.66, f' equals  0.83, estimate theta when amm=1.66,
            # theta near 53 degree
            EdhMAC2 = poub * albedo * (EbnMAC2 * np.cos(np.deg2rad(sza)) + DR + DA) / (1 - poub * albedo) + DR + DA
            EdhMAC2[EdhMAC2 < lower] = lower  # Quality control

            # Global horizontal irradiance
            EghMAC2 = (EbnMAC2 * np.cos(np.deg2rad(sza)) + DR + DA) / (1 - poub * albedo)
            EghMAC2[EghMAC2 < lower] = lower  # Quality control

            EghMAC2[np.isnan(EghMAC2)] = 0
            EbnMAC2[np.isnan(EbnMAC2)] = 0
            EdhMAC2[np.isnan(EdhMAC2)] = 0


            output = [EghMAC2, EbnMAC2, EdhMAC2]

        return output

    def mac2(self, components=3):
        """
        run mac2 model with arguments downloaded in data set

        components = 1, output = Edn
        components = 2, output = [Edn, Edh]
        components = 3, output = [Egh, Edn, Edh]

        matlab version coded by Xixi Sun according to Davies and Mckay 1982 <Estimating solar irradiance and components>

        :return: [Egh, Edn, Edh]
        """
        zenith_angle = latlon2solarzenith(self.lat, self.lon, self.time)
        Eext = data_eext_builder(self.lat.size, self.time)
        [tot_aer_ext, AOD550, Angstrom_exponent, ozone, surface_albedo, water_vapour, pressure,
         nitrogen_dioxide] = self.collect_data()
        earth_radius = np.power(Eext / 1366.1, 0.5)
        ang_alpha = Angstrom_exponent
        ang_beta = AOD550 / (np.power(0.55, -ang_alpha))
        return self.clear_sky_mac2(zenith_angle, earth_radius, pressure, water_vapour, ang_beta, ang_alpha,
                                   surface_albedo, components)
