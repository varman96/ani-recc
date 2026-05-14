# Anime Recommendation System
AniRec is a Anime Recommendation web app that helps users find new anime to watch based on their recently watched anime. It uses the Jikan API to fetch anime metadata and then uses KNN to find similar anime instead of the MAL user voted recommendation system.


## Getting Started

Clone the repo at: https://github.com/varman96/ani-recc and get the following packages:
flask
flask-cors
requests
jikanpy-v4
or instead use: pip install -r requirements.txt

To start the app:
Run python -m src.connection and open index.html in your browser.


## Known Limitations
Results can vary slightly between runs due to Jikan response ordering. It is a alpha so expect bugs. If you find any please report them. 


## Built With

* [flask](https://flask.palletsprojects.com/) - The web framework used
* [jikanpy-v4](https://pypi.org/project/jikanpy-v4/) - Used to fetch anime metadata from the Jikan API
* [python] - Backend
* [HTML/CSS/JS] -Frontend

## Authors

**varman96**


## Contributions
This is a open source project and all contributions are welcome. Open an issue at https://github.com/varman96/ani-recc/issues

## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details


