import os
from typing import (
    Self,
    TypeVar,
    List,
    Literal,
    Callable,
    Optional,
    NamedTuple,
    Union,
    Any,
)
import click

from trakt.movies import Movie as TraktMovie  # type: ignore[import]
from trakt.tv import TVShow as TraktTVShow, TVEpisode as TraktTVEpisode  # type: ignore[import]

T = TypeVar("T")


class MovieId(NamedTuple):
    id: str

    def trakt(self) -> TraktMovie:
        mv = TraktMovie(self.id, year=None, slug=self.id)
        mv._get()
        return mv


class EpisodeId(NamedTuple):
    id: str
    season: int
    episode: int

    @classmethod
    def from_cli(cls, id: str) -> Self:
        return cls(
            id=id,
            season=click.prompt("Season", type=int),
            episode=click.prompt("Episode", type=int),
        )

    def trakt(self) -> TraktTVEpisode:
        from trakt.tv import TVEpisode

        ep = TVEpisode(show=self.id, season=self.season, number=self.episode)
        ep._get()
        return ep


class TVShowId(NamedTuple):
    id: str

    def trakt(self) -> TraktTVShow:
        tv = TraktTVShow(self.id, slug=self.id)
        tv._get()
        return tv


Input = Union[MovieId, EpisodeId, TVShowId]


SEARCH_MAPPING: dict[str, str | None] = {
    "M": "movie",
    "S": "show",
    "I": "show",
    "E": "episode",
    "A": None,
}

allowed = ["M", "S", "I", "E", "A", "U"]


def display_search_entry(entry: Any, *, print_urls: bool = False) -> str:
    from trakt.people import Person as TraktPerson  # type: ignore[import]

    buf: str = ""
    if isinstance(entry, TraktMovie):
        buf += f"Movie:\t{entry.title} ({entry.year})"
        if print_urls and entry.ids.get("ids") and entry.ids["ids"].get("slug"):
            buf += f" | https://trakt.tv/movies/{entry.ids['ids']['slug']}"
        elif print_urls and entry.ext:
            buf += f" | https://trakt.tv/{entry.ext}"
    elif isinstance(entry, TraktTVEpisode):
        buf += f"Episode:\t{entry.show} S{entry.season}E{entry.episode} - {entry.title}"
        if print_urls and entry.ext:
            buf += f" | https://trakt.tv/{entry.ext}"
    elif isinstance(entry, TraktTVShow):
        buf += f"Show:\t{entry.title} ({entry.year})"
        if print_urls and entry.ids.get("ids") and entry.ids["ids"].get("slug"):
            buf += f" | https://trakt.tv/shows/{entry.ids['ids']['slug']}"
        elif print_urls and entry.ext:
            buf += f" | https://trakt.tv/{entry.ext}"
    elif isinstance(entry, TraktPerson):
        buf += f"Person:\t{entry.name}"
        if print_urls and entry.ids.get("ids") and entry.ids["ids"].get("slug"):
            buf += f" | https://trakt.tv/people/{entry.ids['ids']['slug']}"
        elif print_urls and entry.ext:
            buf += f" | https://trakt.tv/{entry.ext}"
    else:
        raise ValueError(f"Invalid entry type: {type(entry)}")

    return buf


def search_trakt(
    *, default_media_type: str | None = None, search_query: str = "", **kwargs: str
) -> Input:
    # handle deprecations
    if "prompt_str" in kwargs and not search_query:
        click.secho("Use 'search_query' instead of 'prompt_str'", fg="yellow")
        search_query = kwargs["prompt_str"]
    # prompt user to ask if they want to search for a
    # particular type of media, else just search for all
    # types
    pressed: str | None = None
    media_type: Optional[str] = None
    if show_url := os.environ.get("TRAKT_WATCH_SHOW"):
        tv_obj = parse_url_to_input(show_url)
        click.echo(f"Show: {tv_obj.id}", err=True)
        return EpisodeId.from_cli(id=tv_obj.id)

    if default_media_type is not None and default_media_type in SEARCH_MAPPING.values():
        media_type = default_media_type
    else:
        click.echo(
            "[M]ovie\n[S]how\n[E]pisode name\nEp[I]sode - Show w/ Season/Episode num\n[U]rl\n[A]ll\nWhat type of media do you want to search for? ",
            nl=False,
        )
        pressed = click.getchar().upper()
        click.echo()
        if pressed.strip() == "":
            click.secho("No input", fg="red")
        elif pressed not in allowed:
            click.secho(
                f"'{pressed}', should be one of ({', '.join(allowed)})",
                fg="red",
            )
        elif pressed == "U":
            urlp = click.prompt("Url", type=str)
            return parse_url_to_input(urlp)
        # 'movie', 'show', 'episode', or 'person'
        pressed = pressed if pressed in allowed else "A"
        media_type = SEARCH_MAPPING.get(pressed)

    from trakt.sync import search  # type: ignore[import]

    if not search_query.strip():
        search_query = click.prompt(f"Search for {media_type or 'all'}", type=str)
    results = search(search_query, search_type=media_type)  # type: ignore[arg-type]

    if not results:
        raise click.ClickException("No results found")

    def _display_items(show_urls: bool, items: List[TraktType]) -> None:
        click.secho("Results:", bold=True)
        for i, result in enumerate(items, 1):
            click.echo(f"{i}: {display_search_entry(result, print_urls=show_urls)}")

    result = pick_item(_display_items, prompt_prefix="Pick result", items=results)
    result._get()

    inp = parse_url_to_input(f"https://trakt.tv/{result.ext}")
    if pressed == "I":
        inp = EpisodeId.from_cli(inp.id)
    return inp


def parse_query_to_arguments(url: str) -> Optional[tuple[str, str | None]]:
    """
    >>> parse_url_to_query('q://the princess bride')
    ('the princess bride', None)
    >>> parse_url_to_query('q+movie://the princess bride')
    ('the princess bride', 'movie')
    >>> parse_url_to_query('q+show://futurama')
    ('futurama', 'show')

    # these should not parse
    >>> parse_url_to_query('the princess bride')
    >>> parse_url_to_query('https://trakt.tv/movies/food-will-win-the-war-1942')
    >>> parse_url_to_query('the princess bride')
    """
    if "://" in url:
        scheme, term = url.split("://", maxsplit=1)
        if term or scheme:
            if scheme == "q":
                return term, None
            media_types = {m for m in SEARCH_MAPPING.values() if m}
            for search_type in media_types:
                if not search_type:
                    continue
                if scheme == f"q+{search_type}":
                    return term, search_type
            else:
                if "+" in scheme:
                    click.secho(
                        f"Warning: '+' in scheme '{scheme}', but did not match known media schemes: {', '.join([f'q+{m}' for m in media_types])}",
                        fg="yellow",
                    )
                return None
    else:
        return None


def parse_url_to_input(url: str) -> Input:
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if parts.netloc != "trakt.tv":
        click.secho(
            f"Warning; Invalid URL netloc: '{parts.netloc}', expected trakt.tv",
            fg="yellow",
            err=True,
        )

    prts = [u.strip() for u in parts.path.split("/") if u.strip()]

    match prts:
        case ["movies", id, *_]:
            return MovieId(id)
        case ["shows", id, "seasons", season, "episodes", episode, *_]:
            return EpisodeId(id, int(season), int(episode))
        case ["shows", id, *_]:
            return TVShowId(id)
        case _:
            raise ValueError(f"Invalid URL parts: {prts}")


TraktType = Union[TraktMovie, TraktTVEpisode, TraktTVShow]


def _handle_pick_result(
    user_input: str,
    items: List[T],
    display_entry: Optional[Callable[[T], str]] = None,
) -> Union[int, Literal["u"], None]:
    if user_input.strip() in {"n", "q"}:
        raise click.Abort()
    if user_input.strip() == "u":
        return "u"
    if user_input.strip().isdigit():
        try:
            return int(user_input)
        except ValueError:
            click.secho(
                f"Could not parse '{user_input}' into a number", fg="red", err=True
            )
    if display_entry is not None:
        for i, item in enumerate(items, 1):
            if user_input.lower() in display_entry(item).lower():
                return i
    click.secho(f"No match for '{user_input}'", fg="red", err=True)
    return None


def pick_item(
    show_options: Callable[[bool, List[T]], None],
    /,
    *,
    prompt_prefix: str,
    items: List[T],
    show_urls_default: bool = False,
    display_entry: Optional[Callable[[T], str]] = None,
) -> T:
    choice: Union[int, Literal["u"], None] = None
    show_urls = show_urls_default
    while choice is None:
        show_options(show_urls, items)
        choice = click.prompt(
            f"{prompt_prefix}, enter 1-{len(items)}{' or show name' if display_entry is not None else ''}, q to quit, u to {'hide' if show_urls else 'show'} URLs",
            default="1",
            value_proc=lambda s: _handle_pick_result(s, items, display_entry),
        )
        if choice is None:
            continue
        if choice == "u":
            show_urls = not show_urls
            choice = None
            continue
        if isinstance(choice, int) and (choice < 1 or choice > len(items)):
            click.secho(f"Invalid choice, must be 1-{len(items)}", fg="red", err=True)
            choice = None

    assert isinstance(choice, int)
    return items[choice - 1]
