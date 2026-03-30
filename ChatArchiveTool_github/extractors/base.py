class BaseExtractor:
    name = "base"

    def detect(self, input_path: str) -> bool:
        return False

    def extract(self, input_path: str, output_dir: str):
        raise NotImplementedError