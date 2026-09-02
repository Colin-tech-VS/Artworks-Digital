from datetime import datetime, timezone

import stripe
from flask import current_app, url_for

from artworks.extensions import db
from artworks.models import Artist, Offer, SubscriptionEvent
from artworks.plans import all_offers, get_offer


def stripe_ready() -> bool:
    return bool(current_app.config.get("STRIPE_SECRET_KEY"))


def _api():
    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]
    return stripe


_BILLING_PATHS = {
    "atelier.billing": "/atelier/offre",
    "atelier.billing_return": "/atelier/offre/retour",
}


def _public_url(endpoint: str) -> str:
    from artworks.seo import canonical_url

    return canonical_url(_BILLING_PATHS.get(endpoint) or url_for(endpoint))


def ensure_offer_priced(offer: Offer) -> None:
    """Crée le Product/Price Stripe s’il manque, pour qu’un checkout parte vraiment."""
    if not stripe_ready() or offer.price_cents <= 0:
        return
    api = _api()
    if not offer.stripe_product_id:
        product = api.Product.create(
            name=f"Artworksdigital {offer.name}",
            description=offer.audience or offer.name,
            metadata={"plan_key": offer.key},
        )
        offer.stripe_product_id = product.id
    price_ok = False
    if offer.stripe_price_id:
        try:
            price = api.Price.retrieve(offer.stripe_price_id)
            price_ok = (
                price.get("unit_amount") == offer.price_cents
                and price.get("active")
                and (price.get("recurring") or {}).get("interval") == "month"
            )
        except Exception:
            price_ok = False
    if not price_ok:
        price = api.Price.create(
            product=offer.stripe_product_id,
            unit_amount=offer.price_cents,
            currency="eur",
            recurring={"interval": "month"},
            metadata={"plan_key": offer.key},
        )
        offer.stripe_price_id = price.id
    db.session.commit()


def sync_offers_to_stripe() -> tuple[bool, str]:
    if not stripe_ready():
        return False, "Clés Stripe absentes."
    try:
        priced = 0
        for offer in all_offers():
            if offer.price_cents <= 0:
                continue
            ensure_offer_priced(offer)
            if offer.stripe_price_id:
                priced += 1
        return True, f"{priced} offre(s) payante(s) synchronisée(s) avec Stripe."
    except Exception as exc:
        db.session.rollback()
        return False, str(exc)


def _customer_for(artist: Artist) -> str:
    api = _api()
    if artist.stripe_customer_id:
        return artist.stripe_customer_id
    customer = api.Customer.create(
        email=artist.email,
        name=artist.display_name,
        metadata={"artist_id": str(artist.id)},
    )
    artist.stripe_customer_id = customer.id
    db.session.commit()
    return customer.id


def checkout_url(artist: Artist, offer: Offer) -> str:
    if not stripe_ready():
        raise RuntimeError("Stripe n’est pas encore branché pour cette offre.")
    ensure_offer_priced(offer)
    if not offer.stripe_price_id:
        raise RuntimeError("Cette offre n’a pas encore de tarif Stripe.")
    api = _api()
    customer = _customer_for(artist)
    session = api.checkout.Session.create(
        mode="subscription",
        customer=customer,
        line_items=[{"price": offer.stripe_price_id, "quantity": 1}],
        success_url=_public_url("atelier.billing_return") + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=_public_url("atelier.billing"),
        allow_promotion_codes=True,
        metadata={"artist_id": str(artist.id), "plan_key": offer.key},
        subscription_data={"metadata": {"artist_id": str(artist.id), "plan_key": offer.key}},
    )
    if not session.url:
        raise RuntimeError("Stripe n’a pas renvoyé d’adresse de paiement.")
    return session.url


def portal_url(artist: Artist) -> str:
    if not stripe_ready() or not artist.stripe_customer_id:
        raise RuntimeError("Aucun client Stripe.")
    api = _api()
    session = api.billing_portal.Session.create(
        customer=artist.stripe_customer_id,
        return_url=_public_url("atelier.billing"),
    )
    return session.url


def apply_plan(artist: Artist, plan_key: str, status: str = "active", subscription_id: str = "", note: str = "") -> None:
    from artworks.emails import send_plan_changed

    previous_key = artist.plan_key
    offer = get_offer(plan_key)
    artist.plan_key = offer.key if offer else "decouverte"
    artist.plan_status = status
    if subscription_id:
        artist.stripe_subscription_id = subscription_id
    if status in {"canceled", "unpaid", "incomplete_expired"} and not artist.plan_override:
        artist.plan_key = "decouverte"
    db.session.add(
        SubscriptionEvent(
            artist_id=artist.id,
            plan_key=artist.plan_key,
            status=status,
            stripe_id=subscription_id,
            note=note[:240],
        )
    )
    db.session.commit()
    if artist.plan_key != previous_key and status not in {"incomplete", "past_due"}:
        final = get_offer(artist.plan_key)
        if final is not None:
            try:
                send_plan_changed(artist, final.name, final.price_label)
            except Exception:
                current_app.logger.exception("Impossible d’envoyer l’e-mail de changement d’offre")


def confirm_checkout(artist: Artist, session_id: str) -> tuple[bool, str]:
    """Applique l’offre au retour de Checkout, même si le webhook tarde."""
    if not stripe_ready() or not (session_id or "").strip():
        return False, "Session Stripe manquante."
    try:
        session = _api().checkout.Session.retrieve(session_id)
    except Exception as exc:
        return False, str(exc)[:180]
    meta = session.get("metadata") or {}
    meta_id = str(meta.get("artist_id") or "")
    if meta_id and meta_id != str(artist.id):
        return False, "Ce paiement n’appartient pas à cet atelier."
    customer = session.get("customer")
    if customer and artist.stripe_customer_id and customer != artist.stripe_customer_id:
        return False, "Ce paiement n’appartient pas à cet atelier."
    paid = session.get("payment_status")
    status = session.get("status")
    if status != "complete" and paid not in {"paid", "no_payment_required"}:
        return False, "Le paiement n’est pas encore confirmé."
    plan_key = meta.get("plan_key") or artist.plan_key
    sub_id = session.get("subscription") or ""
    if isinstance(sub_id, dict):
        sub_id = sub_id.get("id") or ""
    apply_plan(artist, plan_key, status="active", subscription_id=str(sub_id), note="Retour checkout")
    artist.plan_override = False
    if customer and not artist.stripe_customer_id:
        artist.stripe_customer_id = str(customer)
    db.session.commit()
    offer = get_offer(artist.plan_key)
    return True, f"Offre {offer.name} activée." if offer else "Offre mise à jour."


def cancel_to_free(artist: Artist) -> tuple[bool, str]:
    if artist.stripe_subscription_id and stripe_ready():
        try:
            _api().Subscription.cancel(artist.stripe_subscription_id)
        except Exception as exc:
            return False, str(exc)
    artist.stripe_subscription_id = ""
    artist.plan_override = False
    apply_plan(artist, "decouverte", status="canceled", note="Retour offre Découverte")
    return True, "Offre Découverte activée."


def handle_webhook(payload: bytes, signature: str) -> None:
    secret = current_app.config.get("STRIPE_WEBHOOK_SECRET") or ""
    api = _api()
    if secret:
        event = api.Webhook.construct_event(payload, signature, secret)
    else:
        event = api.Event.construct_from(
            __import__("json").loads(payload.decode("utf-8")),
            api.api_key,
        )
    kind = event["type"]
    data = event["data"]["object"]
    if kind == "checkout.session.completed":
        artist = _artist_from_meta(data.get("metadata") or {}, data.get("customer"))
        if artist:
            apply_plan(
                artist,
                (data.get("metadata") or {}).get("plan_key") or artist.plan_key,
                status="active",
                subscription_id=data.get("subscription") or "",
                note="Checkout Stripe",
            )
            artist.plan_override = False
            db.session.commit()
    elif kind in {"customer.subscription.updated", "customer.subscription.created"}:
        artist = _artist_from_subscription(data)
        if artist and not artist.plan_override:
            plan_key = (data.get("metadata") or {}).get("plan_key") or _plan_from_price(data)
            period_end = data.get("current_period_end")
            if period_end:
                artist.plan_period_end = datetime.fromtimestamp(int(period_end), tz=timezone.utc)
            apply_plan(
                artist,
                plan_key or artist.plan_key,
                status=data.get("status") or "active",
                subscription_id=data.get("id") or "",
                note=kind,
            )
    elif kind == "customer.subscription.deleted":
        artist = _artist_from_subscription(data)
        if artist and not artist.plan_override:
            apply_plan(artist, "decouverte", status="canceled", note="Abonnement annulé")
            artist.stripe_subscription_id = ""
            db.session.commit()
    elif kind == "invoice.payment_failed":
        from artworks.emails import send_payment_failed

        artist = _artist_from_customer(data.get("customer"))
        if artist:
            artist.plan_status = "past_due"
            db.session.commit()
            try:
                send_payment_failed(artist)
            except Exception:
                current_app.logger.exception("Impossible d’envoyer l’e-mail de paiement refusé")


def _artist_from_meta(meta: dict, customer_id: str | None) -> Artist | None:
    artist_id = meta.get("artist_id")
    if artist_id:
        artist = db.session.get(Artist, int(artist_id))
        if artist:
            return artist
    return _artist_from_customer(customer_id)


def _artist_from_customer(customer_id: str | None) -> Artist | None:
    if not customer_id:
        return None
    return Artist.query.filter_by(stripe_customer_id=customer_id).first()


def _artist_from_subscription(data: dict) -> Artist | None:
    artist = _artist_from_meta(data.get("metadata") or {}, data.get("customer"))
    if artist:
        return artist
    sub_id = data.get("id")
    if sub_id:
        return Artist.query.filter_by(stripe_subscription_id=sub_id).first()
    return None


def _plan_from_price(data: dict) -> str:
    items = ((data.get("items") or {}).get("data") or [])
    if not items:
        return ""
    price_id = ((items[0] or {}).get("price") or {}).get("id")
    if not price_id:
        return ""
    offer = Offer.query.filter_by(stripe_price_id=price_id).first()
    return offer.key if offer else ""
