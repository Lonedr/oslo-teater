from .base import BaseScraper, Show

__all__ = ["Show", "BaseScraper", "ALL_SCRAPERS", "load_all_scrapers"]


def load_all_scrapers() -> list[type[BaseScraper]]:
    """Lazy import so individual scrapers can be developed in isolation."""
    from .nationaltheatret import NationaltheatretScraper
    from .det_norske_teatret import DetNorskeTeatretScraper
    from .oslo_nye import OsloNyeScraper
    from .black_box import BlackBoxScraper
    from .operaen import OperaenScraper
    from .dramatikkens_hus import DramatikkensHusScraper
    from .riksteatret import RiksteatretScraper
    from .det_andre_teatret import DetAndreTeatretScraper
    from .teater_manu import TeaterManuScraper
    from .nordic_black import NordicBlackScraper
    from .folketeatret import FolketeatretScraper

    return [
        NationaltheatretScraper,
        DetNorskeTeatretScraper,
        OsloNyeScraper,
        BlackBoxScraper,
        OperaenScraper,
        DramatikkensHusScraper,
        RiksteatretScraper,
        DetAndreTeatretScraper,
        TeaterManuScraper,
        NordicBlackScraper,
        FolketeatretScraper,
    ]


ALL_SCRAPERS = load_all_scrapers
