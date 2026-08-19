#===============================================================================
#   File :      roof.py
#   Author :    Olivier Teboul olivier.teboul@ecp.fr
#   Date :      11 august 2008, 12151
#   Class:      Roof
#===============================================================================


class Roof:
    """
    This class provide a factory for rooftop meshes computed from 2D polygons.
    It supports weighted edges. The resulting roof is obtained from straight
    skeleton computation.
    Different kinds of roofs are implemented (playing with speeds) :
        - hip roof
        - gable roof
        - mansard
        - dutch hip
        - 'Haussmannian'
    """
    
    def __init__(self, footprint): pass

    def hip(self):pass    
    def gable(self):pass
    def mansard(self):pass
    def dutch_hip(self):pass
    def haussmannian(self):pass
