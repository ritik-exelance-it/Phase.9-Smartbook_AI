# SmartBook Cinema Help

## What this assistant can do
SmartBook can search the movie catalogue, share details stored for a movie, create a ticket booking, check or cancel a booking belonging to the current customer, answer the policies documented here, and record a request for human support. Movie and booking information comes from the connected application database. If a detail is not in the database or this help guide, SmartBook should say it cannot verify that detail rather than guess.

## Movie catalogue and availability
The movie catalogue is the source of truth for movie titles, genres, show times, ticket prices, and seat availability. A catalogue request returns all matching active titles; an availability request returns all matching titles that currently have seats remaining. These are different questions: a scheduled title may be sold out. Customers can ask for a genre or a specific title to narrow catalogue results. Seat availability can change as bookings are made, so it should be checked against the current database result.

## Making a booking
A booking needs a movie in the catalogue, a customer name, and a positive whole number of seats. The demo accepts no more than ten seats in a single booking. A booking is confirmed only when the database saves it and returns a booking ID. The total is calculated from the movie's stored price per seat and the requested seat count.

## Checking a booking
Customers can check bookings associated with their own application user account. A booking ID helps locate a booking, but it does not grant access to another customer's booking. The database status is the source of truth.

## Cancellation and refunds
The demo can record cancellation for an eligible confirmed booking and update the available-seat count. It reports the booking total as the refund amount for information only. It does not connect to a payment processor, issue money, or guarantee a real refund or its timing. Contact cinema support to confirm payment and refund arrangements.

## Human support
When a customer asks for a person or needs help the assistant cannot provide, SmartBook can create a local escalation record. The demo does not notify or connect to a live support team, so it cannot promise a response time.

## Privacy and permissions
Customers may view or cancel only bookings belonging to their own application user ID. Application code enforces permissions; a role or identity written in a chat message does not grant access. Do not share another customer's private booking information.

## Information not documented
This guide does not specify cinema opening hours, age ratings, accessibility facilities, food and drink options, payment methods, or film runtimes. SmartBook should not make claims about these subjects unless the connected application provides verified information. Offer human support when a customer needs an answer that cannot be verified.
